#!/usr/bin/env python3
"""Compile the lifted C back into a loadable ZDL."""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "toolchain" / "zdl")]
from paths import TI_ROOT  # noqa: E402
from linker import LinkerConfig, link, params_from_manifest  # noqa: E402
from custom_covers import make_cover  # noqa: E402

CL6X = TI_ROOT / "bin" / "cl6x"
CFLAGS = ["--c99", "--opt_level=2", "--fp_mode=strict", "-mv6740", "--abi=eabi",
          "--mem_model:data=far", f"--include_path={TI_ROOT}/include"]


def main():
    manifest = json.loads((HERE / "manifest_pedal.json").read_text(encoding="utf-8"))
    name = manifest["effect_name"]
    audio = manifest["audio_func_name"]
    src = HERE / (name.lower() + ".c")
    obj = HERE / (name.lower() + ".obj")
    out = HERE / (name + "_REBUILT.ZDL")
    subprocess.run([str(CL6X), *CFLAGS, f"--define={name.upper()}_AUDIO_FUNC={audio}",
                    "-c", str(src), f"--output_file={obj}"],
                   check=True, cwd=HERE)
    for junk in ("compiler.opt", "linker.cmd"):
        p = HERE / junk
        if p.exists():
            p.unlink()
    cfg = LinkerConfig(
        materialize_init=True,
        effect_name=name,
        screen_image=make_cover(name, [p["name"] for p in manifest["params"]]),
        audio_func_name=audio,
        gid=manifest["gid"],
        fxid=manifest["fxid"],
        params=params_from_manifest(manifest["params"]),
        obj_path=obj,
        output_path=out,
        fxid_version=manifest.get("fxid_version", "1.00").encode("ascii"),
        flags_byte=manifest.get("flags_byte", 0x01),
        audio_nop=manifest.get("audio_nop", False),
        dsp_cost=manifest.get("dsp_cost", 20.0),
        knob_positions=[(2, 24, 46), (3, 72, 46)],
        allow_fewer_knob_boxes=True,
        use_object_edit_handlers=False,
        synthesize_linesel_edit_handlers=True,
        synth_edit_start_index=2,
        knob3_blob_path="/tmp/__nonexistent__",
    )
    link(cfg)
    print("%s -> %s" % (name, out))


if __name__ == "__main__":
    main()
