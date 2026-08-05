#!/usr/bin/env python3

import argparse
import re
from pathlib import Path
from typing import Dict, Optional, Pattern, Tuple


AUTO_VALUES = {"", "auto"}
SAFE_VALUE = re.compile(r"^[A-Za-z0-9._+-]+$")
SAFE_PATH = re.compile(r"^[A-Za-z0-9._+/-]+$")


def override(value: str) -> Optional[str]:
    value = value.strip()
    return None if value.lower() in AUTO_VALUES else value


def first_match(pattern: str, text: str) -> Optional[str]:
    match = re.search(pattern, text, flags=re.MULTILINE)
    return match.group(1) if match else None


def require_safe(name: str, value: str, pattern: Pattern[str]) -> str:
    if not pattern.fullmatch(value):
        raise ValueError(f"unsafe or invalid {name}: {value!r}")
    return value


def detect_product_device(tree: Path) -> Optional[str]:
    for makefile in sorted(tree.glob("*.mk")):
        value = first_match(
            r"^[ \t]*PRODUCT_DEVICE[ \t]*:=[ \t]*([^ \t\r\n]+)",
            makefile.read_text(encoding="utf-8", errors="replace"),
        )
        if value:
            return value
    return None


def resolve_lunch(requested: Optional[str], detected: Optional[str]) -> str:
    if requested is None:
        if not detected:
            raise ValueError("cannot detect a lunch target from AndroidProducts.mk")
        return detected

    if requested.endswith(("-user", "-userdebug", "-eng")):
        return requested
    if detected and detected.startswith(f"{requested}-") and detected.endswith("-eng"):
        return detected
    return f"{requested}-eng"


def resolve_build_target(
    requested: Optional[str], board_config: str
) -> Tuple[str, str, str]:
    if requested is None:
        if re.search(
            r"^[ \t]*BOARD_INCLUDE_RECOVERY_RAMDISK_IN_VENDOR_BOOT[ \t]*:=[ \t]*true",
            board_config,
            flags=re.MULTILINE,
        ):
            requested = "vendorboot"
        elif re.search(
            r"^[ \t]*BOARD_USES_RECOVERY_AS_BOOT[ \t]*:=[ \t]*true",
            board_config,
            flags=re.MULTILINE,
        ):
            requested = "boot"
        else:
            requested = "recovery"

    normalized = requested.lower().replace("_", "")
    targets = {
        "boot": ("boot", "bootimage", "boot.img"),
        "bootimage": ("boot", "bootimage", "boot.img"),
        "recovery": ("recovery", "recoveryimage", "recovery.img"),
        "recoveryimage": ("recovery", "recoveryimage", "recovery.img"),
        "vendorboot": ("vendorboot", "vendorbootimage", "vendor_boot.img"),
        "vendorbootimage": ("vendorboot", "vendorbootimage", "vendor_boot.img"),
    }
    if normalized not in targets:
        raise ValueError(
            "BUILD_TARGET must be auto, boot, recovery, vendorboot, or an image goal"
        )
    return targets[normalized]


def is_vendor_boot_tree(board_config: str) -> bool:
    """Recognize trees whose recovery ramdisk is packaged in vendor_boot."""
    return bool(re.search(
        r"^[ \t]*BOARD_INCLUDE_RECOVERY_RAMDISK_IN_VENDOR_BOOT[ \t]*:=[ \t]*true",
        board_config,
        flags=re.MULTILINE,
    ))


def resolve(args: argparse.Namespace) -> Dict[str, str]:
    tree = args.tree.resolve()
    board_path = tree / "BoardConfig.mk"
    products_path = tree / "AndroidProducts.mk"
    if not board_path.is_file() or not products_path.is_file():
        raise ValueError("device tree must contain BoardConfig.mk and AndroidProducts.mk")

    board_config = board_path.read_text(encoding="utf-8", errors="replace")
    android_products = products_path.read_text(encoding="utf-8", errors="replace")
    readme_path = tree / "README.md"
    readme = (
        readme_path.read_text(encoding="utf-8", errors="replace")
        if readme_path.is_file()
        else ""
    )

    detected_branch = first_match(r"\b(twrp-[0-9]+(?:\.[0-9]+)?)\b", readme)
    if not detected_branch:
        detected_branch = first_match(
            r"\b(twrp-[0-9]+(?:\.[0-9]+)?)\b", board_config
        )
    manifest_branch = override(args.manifest_branch) or detected_branch or "twrp-12.1"

    detected_path = first_match(
        r"^[ \t]*DEVICE_PATH[ \t]*:=[ \t]*([^ \t\r\n]+)", board_config
    )
    device_path = override(args.device_path) or detected_path
    if not device_path:
        raise ValueError("cannot detect DEVICE_PATH from BoardConfig.mk")

    detected_lunch = first_match(
        r"\b((?:twrp|omni)_[A-Za-z0-9._+-]+-eng)\b", android_products
    )
    lunch_target = resolve_lunch(override(args.makefile_name), detected_lunch)

    detected_device = detect_product_device(tree)
    device_name = override(args.device_name) or detected_device or Path(device_path).name
    build_target, build_goal, artifact_name = resolve_build_target(
        override(args.build_target), board_config
    )

    result = {
        "manifest_branch": require_safe("manifest branch", manifest_branch, SAFE_VALUE),
        "device_path": require_safe("device path", device_path, SAFE_PATH),
        "device_name": require_safe("device name", device_name, SAFE_VALUE),
        "lunch_target": require_safe("lunch target", lunch_target, SAFE_VALUE),
        "build_target": build_target,
        "build_goal": build_goal,
        "artifact_name": artifact_name,
        "is_sprd": str((tree / "prebuilt" / "sourcecode" / "patch.sh").is_file()).lower(),
        "is_vendor_boot": str(is_vendor_boot_tree(board_config)).lower(),
    }
    if not result["device_path"].startswith("device/") or ".." in Path(
        result["device_path"]
    ).parts:
        raise ValueError(f"DEVICE_PATH must stay under device/: {result['device_path']!r}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--manifest-branch", default="auto")
    parser.add_argument("--device-path", default="auto")
    parser.add_argument("--device-name", default="auto")
    parser.add_argument("--makefile-name", default="auto")
    parser.add_argument("--build-target", default="auto")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    result = resolve(args)
    for key, value in result.items():
        print(f"{key}={value}")
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as output:
            for key, value in result.items():
                output.write(f"{key}={value}\n")


if __name__ == "__main__":
    main()
