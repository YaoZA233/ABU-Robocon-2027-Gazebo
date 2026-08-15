#!/usr/bin/env python3
"""Convert the RoboCon STEP assembly to a Gazebo mesh and colored visuals."""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
VENDORED_PACKAGES = SCRIPT_DIR / "python_packages"
if VENDORED_PACKAGES.is_dir():
    sys.path.insert(0, str(VENDORED_PACKAGES))

from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.STEPControl import STEPControl_Reader
from OCP.StlAPI import StlAPI_Writer
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label, TDF_LabelSequence
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_DocumentTool

PROJECT_ROOT = SCRIPT_DIR.parent.parent
MODEL_ROOT = SCRIPT_DIR.parent / "robocon_2027_field"
DEFAULT_OUTPUT = MODEL_ROOT / "meshes" / "robocon_2027_field.stl"
VISUAL_DIR_NAME = "visuals_fixed"
RED = chr(0x7EA2)
BLUE = chr(0x84DD)


def discover_step() -> Path:
    candidates = sorted(PROJECT_ROOT.rglob("*.STEP"), key=lambda path: path.stat().st_size, reverse=True)
    if not candidates:
        raise FileNotFoundError(f"No STEP file found under {PROJECT_ROOT}")
    return candidates[0]


def read_binary_stl(path: Path) -> tuple[int, list[float]]:
    with path.open("rb") as stream:
        if len(stream.read(80)) != 80:
            raise ValueError("STL header is incomplete")
        triangle_count = struct.unpack("<I", stream.read(4))[0]
        minimum = [float("inf")] * 3
        maximum = [float("-inf")] * 3
        for _ in range(triangle_count):
            record = stream.read(50)
            if len(record) != 50:
                raise ValueError("STL triangle data is incomplete")
            values = struct.unpack("<12fH", record)
            for offset in (3, 6, 9):
                for axis in range(3):
                    minimum[axis] = min(minimum[axis], values[offset + axis])
                    maximum[axis] = max(maximum[axis], values[offset + axis])
        if path.stat().st_size != 84 + triangle_count * 50:
            raise ValueError("STL is not a valid binary STL")
        return triangle_count, minimum + maximum


def count_subshapes(shape, shape_type) -> int:
    explorer = TopExp_Explorer(shape, shape_type)
    count = 0
    while explorer.More():
        count += 1
        explorer.Next()
    return count


def label_name(label: TDF_Label) -> str:
    attribute = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), attribute):
        return attribute.Get().ToExtString()
    return "unnamed"


def read_colored_components(source: Path):
    """Read component placements from STEP's XCAF assembly tree."""
    application = XCAFApp_Application.GetApplication_s()
    document = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    application.NewDocument(TCollection_ExtendedString("MDTV-XCAF"), document)
    reader = STEPCAFControl_Reader()
    reader.SetColorMode(True)
    reader.SetNameMode(True)
    if reader.ReadFile(str(source)) != IFSelect_RetDone or not reader.Transfer(document):
        raise RuntimeError("OpenCascade XCAF failed to read the STEP assembly")

    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    free_shapes = TDF_LabelSequence()
    shape_tool.GetFreeShapes(free_shapes)
    components = TDF_LabelSequence()
    for index in range(1, free_shapes.Length() + 1):
        root = free_shapes.Value(index)
        if shape_tool.IsAssembly_s(root):
            shape_tool.GetComponents_s(root, components, True)
        else:
            components.Append(root)

    result = []
    for index in range(1, components.Length() + 1):
        component = components.Value(index)
        referred = TDF_Label()
        name = label_name(referred) if shape_tool.GetReferredShape_s(component, referred) else label_name(component)
        shape = shape_tool.GetShape_s(component)
        if not shape.IsNull():
            result.append((name, shape))
    return result


def material_for_name(name: str) -> tuple[str, str, str, str]:
    # RGB values come from section 14 of the supplied rules PDF. STEP keeps
    # component names but not the original SolidWorks RGB attributes.
    palettes = {
        "ground_red": ("0.941176 0.823529 0.823529 1", "0.941176 0.823529 0.823529 1", "0.16 0.12 0.12 1"),
        "ground_blue": ("0.666667 0.823529 0.901961 1", "0.666667 0.823529 0.901961 1", "0.10 0.14 0.18 1"),
        "shared": ("0.960784 0.941176 0.784314 1", "0.960784 0.941176 0.784314 1", "0.16 0.15 0.08 1"),
        "level_red": ("0.921569 0.705882 0.627451 1", "0.921569 0.705882 0.627451 1", "0.16 0.10 0.08 1"),
        "level_blue": ("0.588235 0.843137 0.862745 1", "0.588235 0.843137 0.862745 1", "0.08 0.14 0.15 1"),
        "bright_red": ("0.874510 0.133333 0.133333 1", "0.874510 0.133333 0.133333 1", "0.18 0.01 0.01 1"),
        "bright_blue": ("0.196078 0.000000 1.000000 1", "0.196078 0.000000 1.000000 1", "0.02 0.01 0.18 1"),
        "green": ("0.156863 0.392157 0.196078 1", "0.156863 0.392157 0.196078 1", "0.02 0.10 0.04 1"),
        "boundary_brown": ("0.392157 0.243137 0.000000 1", "0.392157 0.243137 0.000000 1", "0.05 0.025 0.005 1"),
        "stone": ("0.854902 0.647059 0.125490 1", "0.854902 0.647059 0.125490 1", "0.18 0.12 0.02 1"),
        "level_neutral": ("0.745098 0.745098 0.725490 1", "0.745098 0.745098 0.725490 1", "0.12 0.12 0.11 1"),
        "stair_red": ("0.921569 0.705882 0.627451 1", "0.921569 0.705882 0.627451 1", "0.16 0.10 0.08 1"),
        "stair_blue": ("0.588235 0.843137 0.862745 1", "0.588235 0.843137 0.862745 1", "0.08 0.14 0.15 1"),
    }
    if name == RED + "1区":
        key = "ground_red"
    elif name == BLUE + "1区":
        key = "ground_blue"
    elif name == "1区储存区-" + RED:
        key = "ground_red"
    elif name == "1区储存区-" + BLUE:
        key = "ground_blue"
    elif name == RED + "2区":
        key = "level_red"
    elif name == BLUE + "2区":
        key = "level_blue"
    elif name == "1区-灵石基座" or name == "3区-中央基座":
        key = "boundary_brown"
    elif name == "灵石":
        key = "stone"
    elif name in {"台阶-" + RED, "二层台阶-" + RED}:
        key = "stair_red"
    elif name in {"台阶-" + BLUE, "二层台阶-" + BLUE}:
        key = "stair_blue"
    elif name == "建造点":
        key = "green"
    elif "栅栏" in name:
        key = "boundary_brown"
    elif RED in name:
        key = "bright_red"
    elif BLUE in name:
        key = "bright_blue"
    elif "共享区" in name:
        key = "shared"
    else:
        key = "level_neutral"
    ambient, diffuse, specular = palettes[key]
    return key, ambient, diffuse, specular


def write_colored_model_sdf(visuals: list[dict]) -> None:
    blocks = []
    for item in visuals:
        pose = f'\n        <pose>{item["pose"]}</pose>' if item.get("pose") else ""
        blocks.append(
            f'''      <visual name="component_{item["index"]:03d}_{item["material"]}">
        <cast_shadows>{str(item.get("cast_shadows", False)).lower()}</cast_shadows>{pose}
        <geometry>
          <mesh>
            <uri>model://robocon_2027_field/{VISUAL_DIR_NAME}/component_{item["index"]:03d}.stl</uri>
            <scale>0.001 0.001 0.001</scale>
          </mesh>
        </geometry>
        <material>
          <ambient>{item["ambient"]}</ambient>
          <diffuse>{item["diffuse"]}</diffuse>
          <specular>{item["specular"]}</specular>
        </material>
      </visual>'''
        )
    # Add thin visual-only outlines. The fills remain the exact official RGB;
    # outlines make coplanar storage zones and adjacent same-color stair faces
    # readable in Gazebo without changing collision geometry.
    _, brown_ambient, brown_diffuse, brown_specular = material_for_name("1区栅栏")

    def box_visual(name: str, pose: str, size: str) -> str:
        return f'''      <visual name="{name}">
        <cast_shadows>true</cast_shadows>
        <pose>{pose}</pose>
        <geometry><box><size>{size}</size></box></geometry>
        <material>
          <ambient>{brown_ambient}</ambient>
          <diffuse>{brown_diffuse}</diffuse>
          <specular>{brown_specular}</specular>
        </material>
      </visual>'''

    # CAD-local coordinates in metres. The link pose below performs the same
    # Y-up to Z-up rotation used by the component meshes.
    for label, center_x in (("red", -4.5), ("blue", 4.5)):
        blocks.extend(
            [
                box_visual(f"storage_{label}_outline_front", f"{center_x:.3f} 0.027 -5.495 0 0 0", "2.000 0.004 0.010"),
                box_visual(f"storage_{label}_outline_back", f"{center_x:.3f} 0.027 -4.505 0 0 0", "2.000 0.004 0.010"),
                box_visual(f"storage_{label}_outline_left", f"{center_x - 0.995:.3f} 0.027 -5.000 0 0 0", "0.010 0.004 1.000"),
                box_visual(f"storage_{label}_outline_right", f"{center_x + 0.995:.3f} 0.027 -5.000 0 0 0", "0.010 0.004 1.000"),
            ]
        )

    text = f'''<?xml version="1.0"?>
<sdf version="1.7">
  <model name="robocon_2027_field">
    <static>true</static>
    <link name="field">
      <!-- CAD uses millimetres and Y-up; Gazebo uses metres and Z-up. -->
      <pose>0 0 0.025 1.5707963267948966 0 0</pose>
      <collision name="field_collision">
        <geometry>
          <mesh>
            <uri>model://robocon_2027_field/meshes/robocon_2027_field.stl</uri>
            <scale>0.001 0.001 0.001</scale>
          </mesh>
        </geometry>
        <max_contacts>20</max_contacts>
        <surface>
          <friction><ode><mu>0.8</mu><mu2>0.8</mu2></ode></friction>
          <contact><ode><kp>10000000</kp><kd>1</kd><max_vel>0.1</max_vel><min_depth>0.001</min_depth></ode></contact>
        </surface>
      </collision>
{chr(10).join(blocks)}
    </link>
  </model>
</sdf>
'''
    (MODEL_ROOT / "model.sdf").write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--linear-deflection-mm", type=float, default=2.0)
    parser.add_argument("--angular-deflection-rad", type=float, default=0.25)
    args = parser.parse_args()

    source = (args.source or discover_step()).resolve()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    visuals_root = MODEL_ROOT / VISUAL_DIR_NAME
    visuals_root.mkdir(parents=True, exist_ok=True)
    # Existing generated meshes can be read-only/held by a viewer on Windows;
    # the writer below overwrites the fixed component_001..035 paths in place.

    reader = STEPControl_Reader()
    if reader.ReadFile(str(source)) != IFSelect_RetDone or reader.TransferRoots() == 0:
        raise RuntimeError("OpenCascade failed to read the STEP assembly")
    shape = reader.OneShape()
    if shape.IsNull():
        raise RuntimeError("STEP transfer produced a null shape")

    source_box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, source_box, True, False)
    source_bounds = list(source_box.Get())
    mesher = BRepMesh_IncrementalMesh(shape, args.linear_deflection_mm, False, args.angular_deflection_rad, True)
    mesher.Perform()
    if not mesher.IsDone():
        raise RuntimeError("OpenCascade meshing did not finish")
    writer = StlAPI_Writer()
    writer.ASCIIMode = False
    if not writer.Write(shape, str(output)):
        raise RuntimeError("OpenCascade STL writer failed")

    components = read_colored_components(source)
    visuals = []
    for index, (name, component_shape) in enumerate(components, 1):
        component_path = visuals_root / f"component_{index:03d}.stl"
        component_mesher = BRepMesh_IncrementalMesh(component_shape, args.linear_deflection_mm, False, args.angular_deflection_rad, True)
        component_mesher.Perform()
        if not component_mesher.IsDone() or not writer.Write(component_shape, str(component_path)):
            raise RuntimeError(f"Failed to mesh component {index}: {name}")
        material, ambient, diffuse, specular = material_for_name(name)
        triangles, bounds = read_binary_stl(component_path)
        visuals.append({
            "index": index,
            "name": name,
            "material": material,
            "ambient": ambient,
            "diffuse": diffuse,
            "specular": specular,
            "cast_shadows": material in {"stair_red", "stair_blue"},
            "pose": "0 0.0005 0 0 0 0" if "储存区" in name else None,
            "triangle_count": triangles,
            "bounds_mm": bounds,
        })
    write_colored_model_sdf(visuals)

    triangle_count, stl_bounds = read_binary_stl(output)
    minimum, maximum = stl_bounds[:3], stl_bounds[3:]
    dimensions_m = [(maximum[i] - minimum[i]) * 0.001 for i in range(3)]
    stats = {
        "source": str(source), "mesh": str(output), "step_roots": 1,
        "step_solid_count": count_subshapes(shape, TopAbs_SOLID),
        "step_shell_count": count_subshapes(shape, TopAbs_SHELL), "step_face_count": count_subshapes(shape, TopAbs_FACE),
        "triangle_count": triangle_count, "linear_deflection_mm": args.linear_deflection_mm,
        "angular_deflection_rad": args.angular_deflection_rad, "source_bounds_mm": source_bounds,
        "stl_bounds_mm": stl_bounds, "stl_dimensions_m_xyz": dimensions_m,
        "gazebo_dimensions_m_xyz_after_x_90deg": [dimensions_m[0], dimensions_m[2], dimensions_m[1]],
        "gazebo_bounds_m_xyz_after_pose": [minimum[0]*0.001, -maximum[2]*0.001, minimum[1]*0.001+0.025, maximum[0]*0.001, -minimum[2]*0.001, maximum[1]*0.001+0.025],
        "mesh_bytes": output.stat().st_size, "visual_component_count": len(visuals),
        "visual_decoration_count": 8,
        "sdf_visual_count": len(visuals) + 8,
        "color_source": "robocon2027_rules_pdf_section_14",
        "visual_material_counts": {
            material: sum(item["material"] == material for item in visuals)
            for material in sorted({item["material"] for item in visuals})
        },
        "visual_components": visuals,
    }
    (MODEL_ROOT / "mesh_stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
