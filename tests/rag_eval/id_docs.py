"""The ID set (AI-12, AI-31): files that are almost the same except for a code, a number or an
exact phrase, so only exact matching finds the right one. Written fresh for every run, the same
every time (queries_ids.json asks about them).

    invoices/   eight invoices that differ only in their number and total
    devices/    six warranty cards that differ only in the serial number
    orders/     six order confirmations with long order numbers
    firmware/   release notes for v2.3.1, v2.3.10, v2.13.1 and v3.2.1
    letters/    four letters using the same words in a different order
"""

from __future__ import annotations

import os

INVOICES = [
    ("0417", "1,240.00"),
    ("0471", "1,420.00"),
    ("0423", "1,320.00"),
    ("0432", "1,230.00"),
    ("0714", "2,140.00"),
    ("0741", "2,410.00"),
    ("1047", "4,120.00"),
    ("1074", "4,210.00"),
]
SERIALS = ["SN-7XK2-90QA", "SN-7XK2-90QB", "SN-7XK2-09QA", "SN-7KX2-90QA", "SN-X7K2-90QA", "SN-7XK2-90AQ"]
ORDERS = ["58213301", "58213310", "58231301", "85213301", "58213031", "58213300"]
FIRMWARE = {
    "v2.3.1": "fixes the fan curve after waking from sleep",
    "v2.3.10": "adds support for 24 TB drives",
    "v2.13.1": "updates the web interface translations",
    "v3.2.1": "removes the old FTP service",
}
LETTERS = {
    "lantern_a.md": "Please keep the blue lantern lit by the gate until we are home.",
    "lantern_b.md": "Please keep the lantern lit, the blue gate is open until we are home.",
    "lantern_c.md": "Keep the gate lit, please; the blue lantern stays home until we are back.",
    "lantern_d.md": "The blue lantern by the gate: please keep it lit until we are home.",
}


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def build(root: str) -> list[str]:
    """Write the ID files under root/ids; returns their paths relative to root."""
    out = []
    base = os.path.join(root, "ids")
    for number, total in INVOICES:
        rel = f"ids/invoices/invoice_{number}.md"
        _write(
            os.path.join(root, rel),
            (
                f"# Invoice INV-2025-{number}\n\nCustomer: Garden Supplies Ltd, 12 Mill Lane.\n"
                "Items: 4 raised beds, 2 water butts, delivery.\n"
                f"Total due: EUR {total}. Payment within 30 days to the account on file.\n"
            ),
        )
        out.append(rel)
    for serial in SERIALS:
        rel = f"ids/devices/warranty_{serial.lower()}.md"
        _write(
            os.path.join(root, rel),
            (
                "# Warranty card\n\nProduct: 8 TB NAS hard drive, 5400 rpm.\n"
                f"Serial number: {serial}\nWarranty: three years from the date of purchase.\n"
            ),
        )
        out.append(rel)
    for order in ORDERS:
        rel = f"ids/orders/order_{order}.md"
        _write(
            os.path.join(root, rel),
            (
                f"# Order confirmation\n\nOrder number {order}.\nThank you for your order of one USB-C cable "
                "and one power adapter. It ships within two working days.\n"
            ),
        )
        out.append(rel)
    for version, change in FIRMWARE.items():
        rel = f"ids/firmware/release_{version.replace('.', '_')}.md"
        _write(os.path.join(root, rel), f"# Firmware {version}\n\nThis firmware release {change}.\n")
        out.append(rel)
    for name, text in LETTERS.items():
        rel = f"ids/letters/{name}"
        _write(os.path.join(root, rel), f"# A note for the neighbours\n\n{text}\n")
        out.append(rel)
    os.makedirs(base, exist_ok=True)
    return out
