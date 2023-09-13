#!/usr/bin/env python
# coding=utf-8
#
# Copyright (C) 2023, Evan McKinney, evmckinney9@gmail.com
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#
"""
An Inkscape extension to create animated SVG files from layers.
"""
from pathlib import Path
import inkex
from inkex.bezier import csplength
from lxml import etree
import collections
import sys
from copy import deepcopy

# Namedtuple to represent a Layer
Layer = collections.namedtuple("Layer", ["id", "label"])
# Namedtuple to represent an Export item
Export = collections.namedtuple("Export", ["visible_layers", "file_name"])


class TakitaroExtension(inkex.EffectExtension):
    def add_arguments(self, parser):
        super().add_arguments(parser)
        # Command line arguments
        parser.add_argument(
            "-o",
            "--output-dir",
            type=Path,
            default="~/",
            help="Path to output directory",
        )
        parser.add_argument(
            "--prefix", default="", help="Prefix for exported file names"
        )
        parser.add_argument(
            "--enumerate",
            type=inkex.Boolean,
            help="Extra prefix for exported file names",
        )
        parser.add_argument(
            "--include_background",
            type=inkex.Boolean,
            help="Include bottom-most layer as a fixed background in all exported layers.",
        )
        parser.add_argument(
            "--animation_style",
            type=str,
            default="ease",
            help="CSS animation style for layers (ease, ease-in, ease-out, linear).",
        )

    def get_layer_list(self):
        """Retrieve a list of layers in the source SVG file."""
        svg_layers = self.document.xpath(
            '//svg:g[@inkscape:groupmode="layer"]', namespaces=inkex.NSS
        )
        layer_list = [
            Layer(
                layer.attrib["id"],
                layer.attrib.get(inkex.addNS("label", "inkscape"), "").lower(),
            )
            for layer in reversed(svg_layers)
        ]
        return layer_list

    def get_export_list(self, layer_list):
        """Generate a list of layers that need to be exported as separate SVG files."""
        export_list = []
        for counter, layer in enumerate(layer_list):
            if counter == 0 and not self.options.include_background:
                continue
            visible_layers = {
                other_layer.id
                for idx, other_layer in enumerate(layer_list)
                if idx <= counter
            }
            layer_name = (
                f"{counter+1:03d}_{layer.label}"
                if self.options.enumerate
                else layer.label
            )
            export_list.append(Export(visible_layers, layer_name))
        return export_list

    def get_all_paths_in_layer(self, layer_element):
        """Retrieve all path elements within a given layer."""
        return layer_element.xpath(".//svg:path", namespaces=inkex.NSS)

    def add_animation(self, to_animate, anim_id):
        """Add animation to paths within a layer."""
        lengths = [
            self.get_animatable_length(element)
            for element in to_animate
            if element.tag == inkex.addNS("path", "svg")
        ]

        if not lengths:
            inkex.errormsg(
                "Please convert all objects to paths before running this extension."
            )
            return

        total_length = sum(lengths)
        end_percent = 0
        for index, length in enumerate(lengths):
            start_percent = end_percent
            end_percent += round(length / total_length * 100, 3)
            end_percent = min(end_percent, 100)
            self.animate_path(
                to_animate[index],
                start_percent,
                end_percent,
                length,
                length,
                0,
                anim_id,
            )

        animation_style_content = f"""
        .{anim_id} {{
          animation-duration: 1s;
          animation-timing-function: {self.options.animation_style};
          animation-delay: 0s;
          animation-iteration-count: 1;
          animation-fill-mode: forwards;
          }}\n"""
        self.add_or_replace_style_tag(anim_id, animation_style_content)

    def animate_path(
        self,
        element,
        start_percent,
        end_percent,
        length,
        start_length,
        end_length,
        anim_id,
    ):
        """Helper function to add animation to an individual path."""
        path_id = element.get("id")
        path_style_content = f"""
        #{path_id} {{
          animation-name: {path_id};
          stroke-dasharray: {length} !important;
        }}
        @keyframes {path_id} {{
          0%, {start_percent}% {{stroke-dashoffset: {start_length};}}
          {end_percent}%, 100% {{stroke-dashoffset: {end_length};}}
        }}\n"""
        self.add_or_replace_style_tag(
            f"pathanim_{path_id}", path_style_content
        )
        element.set("class", anim_id)

    def get_animatable_length(self, elem):
        """Calculate the length of a path for animation."""
        csp = elem.path.to_superpath()
        subpath_lengths, path_length = csplength(csp)
        if len(subpath_lengths) > 1:
            path_length = max(
                sum(subpath_segments) for subpath_segments in subpath_lengths
            )
        return path_length

    def add_or_replace_style_tag(self, tag_id, content):
        """Add or replace a style tag in the SVG."""
        # Find all style tags in the SVG document
        style_tags = self.root.xpath("//svg:style", namespaces=inkex.NSS)

        # Find the first tag with the specified id, if any
        old_tag = next(
            (tag for tag in style_tags if tag.get("id") == tag_id), None
        )

        # If a tag with the specified id is found, remove it
        if old_tag is not None:
            self.root.remove(old_tag)

        # Add a new style tag with the specified id and content
        style_tag = etree.SubElement(self.root, "style", {"id": tag_id})
        style_tag.text = content

    def export_to_svg(self, export_item: Export, output_dir: Path):
        """
        Export a current document to an Inkscape SVG file.
        :arg Export export_item: Export description.
        :arg Path output_dir: Path to an output directory.
        :return Output file path.
        """
        # Create a deep copy of the current SVG document
        document = deepcopy(self.document)

        # Only process high-level layers, treat sub-layers as groups
        svg_layers = document.xpath(
            '//svg:g[@inkscape:groupmode="layer"]', namespaces=inkex.NSS
        )

        for layer in svg_layers:
            if layer.attrib["id"] in export_item.visible_layers:
                layer.attrib["style"] = "display:inline"
            else:
                layer.attrib["style"] = "display:none"

        output_file = output_dir / (export_item.file_name + ".svg")
        document.write(str(output_file))

        return output_file

    def effect(self):
        """Main function to execute the extension."""
        self.root = self.document.getroot()
        layer_list = self.get_layer_list()
        export_list = self.get_export_list(layer_list)
        for idx, export_item in enumerate(export_list):
            for layer in layer_list:
                layer_tag = self.svg.getElementById(layer.id)
                layer_tag.set(
                    "style",
                    "display:inline"
                    if layer.id in export_item.visible_layers
                    else "display:none",
                )
            top_layer_id = list(export_item.visible_layers)[-1]
            top_layer_tag = self.svg.getElementById(top_layer_id)

            # Get all paths within the top layer
            to_animate = self.get_all_paths_in_layer(top_layer_tag)

            self.add_animation(to_animate, anim_id=f"anim_{idx}")

            # Export the SVG after modifying it
            self.export_to_svg(export_item, self.options.output_dir)

        self.msg(f"Processed {len(export_list)} export layers.")


if __name__ == "__main__":
    try:
        TakitaroExtension().run()
    except Exception as e:
        import traceback

        inkex.errormsg(traceback.format_exc())
        sys.exit(1)
