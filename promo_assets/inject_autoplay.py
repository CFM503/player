"""Inject timed slide transitions; play once and stay on the last slide (no loop, no auto-close)."""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path


def _slide_index(name: str) -> int:
    m = re.fullmatch(r"ppt/slides/slide(\d+)\.xml", name)
    return int(m.group(1)) if m else 0


def inject(src: Path, dst: Path, advance_ms: int) -> None:
    # loop=0：不循环；播完停在最后一页（最后一页关闭自动换页）
    show_pr = (
        '<p:showPr loop="0" showNarration="0" showAnimation="1" useTimings="1">'
        "<p:present/></p:showPr>"
    )
    # 前几页：定时自动前进；最后一页：不自动前进，停住不关放映
    transition_auto = (
        f'<p:transition spd="med" advClick="0" advTm="{advance_ms}">'
        f"<p:fade/></p:transition>"
    )
    transition_hold = (
        '<p:transition spd="med" advClick="1">'
        "<p:fade/></p:transition>"
    )

    with zipfile.ZipFile(src, "r") as zin:
        infos = zin.infolist()
        slide_names = sorted(
            (n for n in zin.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
            key=_slide_index,
        )
        last_slide = slide_names[-1] if slide_names else ""

        contents: dict[str, bytes] = {}
        for info in infos:
            if info.is_dir():
                contents[info.filename] = b""
                continue
            data = zin.read(info.filename)
            name = info.filename

            if re.fullmatch(r"ppt/slides/slide\d+\.xml", name):
                xml = data.decode("utf-8")
                xml = re.sub(r"<p:transition\b[^>]*/>", "", xml)
                xml = re.sub(r"<p:transition\b[\s\S]*?</p:transition>", "", xml)
                tr = transition_hold if name == last_slide else transition_auto
                if "</p:sld>" in xml:
                    xml = xml.replace("</p:sld>", f"{tr}</p:sld>")
                data = xml.encode("utf-8")

            elif name == "ppt/presentation.xml":
                xml = data.decode("utf-8")
                xml = re.sub(r"<p:showPr\b[^>]*/>", "", xml)
                xml = re.sub(r"<p:showPr\b[\s\S]*?</p:showPr>", "", xml)
                if "</p:presentation>" in xml:
                    xml = xml.replace("</p:presentation>", f"{show_pr}</p:presentation>")
                data = xml.encode("utf-8")

            contents[name] = data

        with zipfile.ZipFile(dst, "w") as zout:
            for info in infos:
                name = info.filename
                if name.endswith("/"):
                    continue
                data = contents[name]
                new_info = zipfile.ZipInfo(filename=name, date_time=info.date_time)
                new_info.compress_type = info.compress_type or zipfile.ZIP_DEFLATED
                new_info.external_attr = info.external_attr
                new_info.create_system = info.create_system
                zout.writestr(new_info, data)

    print(
        f"Injected autoplay ({advance_ms} ms/slide, no loop, hold last) → {dst}"
    )


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: inject_autoplay.py <src.pptx> <dst.pptx> <advance_ms>")
        sys.exit(2)
    inject(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]))
