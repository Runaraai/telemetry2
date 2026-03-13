"""
Parsers for nvidia-smi text output.

Used by the Tune Instance feature to extract supported clock speeds and power limits
from nvidia-smi -q -d SUPPORTED_CLOCKS and nvidia-smi -q -d POWER outputs.
"""

import re
from typing import List, Optional, Tuple


def parse_supported_clocks(raw_output: str) -> List[int]:
    """
    Parse nvidia-smi -q -d SUPPORTED_CLOCKS output to extract Graphics frequencies (MHz).

    The output typically looks like:
        Supported Clocks
            Memory           : 3400 MHz
                Graphics     : 1980 MHz
                Graphics     : 1972 MHz
                Graphics     : 1965 MHz
            Memory           : 3200 MHz
                Graphics     : 1980 MHz
                ...

    Returns a deduplicated, descending-sorted list of supported Graphics clock frequencies in MHz.
    Returns empty list if parsing fails or no Graphics clocks found.
    """
    if not raw_output or not raw_output.strip():
        return []

    # Match lines like "Graphics     : 1980 MHz" or "Graphics     : 1980.00 MHz"
    pattern = re.compile(r"Graphics\s+:\s*(\d+)(?:\.\d+)?\s*MHz", re.IGNORECASE)
    matches = pattern.findall(raw_output)

    if not matches:
        return []

    # Convert to int, deduplicate, sort descending (max first)
    frequencies = sorted(set(int(m) for m in matches), reverse=True)
    return frequencies


def parse_power_limits(raw_output: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Parse nvidia-smi -q -d POWER output to extract power limit values.

    The output typically looks like:
        Power Draw                  : 50.00 W
        Power Limit                 : 350.00 W
        Default Power Limit         : 350.00 W
        Max Power Limit             : 350.00 W
        Min Power Limit             : 100.00 W

    Returns (current_power_limit, max_power_limit, min_power_limit) in watts.
    Any value may be None if not found.
    """
    if not raw_output or not raw_output.strip():
        return None, None, None

    current: Optional[float] = None
    max_limit: Optional[float] = None
    min_limit: Optional[float] = None

    # "Current Power Limit" (H100, newer) or "Power Limit" (older) = effective power limit
    current_match = re.search(
        r"Current Power Limit\s+:\s*([\d.]+)\s*W",
        raw_output,
        re.IGNORECASE,
    )
    if not current_match:
        current_match = re.search(
            r"Power Limit\s+:\s*([\d.]+)\s*W",
            raw_output,
            re.IGNORECASE,
        )
    if current_match:
        try:
            current = float(current_match.group(1))
        except ValueError:
            pass

    # "Max Power Limit"
    max_match = re.search(
        r"Max Power Limit\s+:\s*([\d.]+)\s*W",
        raw_output,
        re.IGNORECASE,
    )
    if max_match:
        try:
            max_limit = float(max_match.group(1))
        except ValueError:
            pass

    # Fallback: if Max Power Limit not found, some GPUs use "Enforced Power Limit"
    if max_limit is None:
        enforced_match = re.search(
            r"Enforced Power Limit\s+:\s*([\d.]+)\s*W",
            raw_output,
            re.IGNORECASE,
        )
        if enforced_match:
            try:
                max_limit = float(enforced_match.group(1))
            except ValueError:
                pass

    min_match = re.search(
        r"Min Power Limit\s+:\s*([\d.]+)\s*W",
        raw_output,
        re.IGNORECASE,
    )
    if min_match:
        try:
            min_limit = float(min_match.group(1))
        except ValueError:
            pass

    return current, max_limit, min_limit


def parse_current_graphics_clock(raw_output: str) -> Optional[int]:
    """
    Parse nvidia-smi -q -d CLOCK output to get the current Graphics/SM clock (MHz).

    Used to show "Current / Max" in the UI. Looks for "Graphics" or "SM Clock" under
    "Applications Clocks" or "Clocks" section.

    Returns the current graphics clock in MHz, or None if not found.
    """
    if not raw_output or not raw_output.strip():
        return None

    # Prefer Applications Clocks > Graphics
    app_match = re.search(
        r"Applications Clocks\s+.*?Graphics\s+:\s*(\d+)\s*MHz",
        raw_output,
        re.DOTALL | re.IGNORECASE,
    )
    if app_match:
        try:
            return int(app_match.group(1))
        except ValueError:
            pass

    # Fallback: Clocks section, Graphics
    graphics_match = re.search(
        r"^\s*Graphics\s+:\s*(\d+)\s*MHz",
        raw_output,
        re.MULTILINE | re.IGNORECASE,
    )
    if graphics_match:
        try:
            return int(graphics_match.group(1))
        except ValueError:
            pass

    return None
