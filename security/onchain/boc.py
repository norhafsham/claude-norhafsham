"""A minimal read-only BoC parser -- enough to walk a router's storage cell.

The TON libraries that would do this properly are TypeScript. Rather than make the
chain-side check depend on a node_modules tree, this implements just the slice of
the bag-of-cells format needed here: deserialise, expose refs, and read the library
hash out of an exotic library cell.

Deliberately not a general implementation. It ignores the index and CRC, and does
not reconstruct cell hashes -- for library cells the hash we care about is carried
in the cell's data, so nothing needs hashing.

Format reference: https://docs.ton.org/develop/data-formats/cell-boc
"""

from __future__ import annotations

from dataclasses import dataclass, field

BOC_MAGIC = b"\xb5\xee\x9c\x72"
LIBRARY_CELL = 0x02


@dataclass
class Cell:
    data: bytes
    bit_length: int
    exotic: bool
    refs: list[Cell] = field(default_factory=list)

    @property
    def cell_type(self) -> int | None:
        """The exotic cell type tag (first byte), or None for ordinary cells."""
        return self.data[0] if self.exotic and self.data else None

    def library_hash(self) -> str | None:
        """The 32-byte code hash carried by an exotic library cell, hex encoded."""
        if self.cell_type != LIBRARY_CELL or len(self.data) < 33:
            return None
        return self.data[1:33].hex()


def deserialize(raw: bytes) -> Cell:
    """Parse a bag of cells and return its first root."""
    if raw[:4] != BOC_MAGIC:
        raise ValueError(f"not a bag of cells: magic {raw[:4].hex()}")

    flags = raw[4]
    ref_size = flags & 0b111
    has_idx = bool(flags & 0b1000_0000)
    has_crc = bool(flags & 0b0100_0000)
    off_size = raw[5]

    p = 6

    def take_int(width: int) -> int:
        nonlocal p
        v = int.from_bytes(raw[p : p + width], "big")
        p += width
        return v

    cell_count = take_int(ref_size)
    root_count = take_int(ref_size)
    take_int(ref_size)  # absent
    take_int(off_size)  # total cell data size

    roots = [take_int(ref_size) for _ in range(root_count)]
    if has_idx:
        p += cell_count * off_size

    # Cells are stored in topological order: a cell's refs always appear after it,
    # so parse the flat list first and only then wire the references up.
    raw_cells: list[tuple[Cell, list[int]]] = []
    for _ in range(cell_count):
        d1, d2 = raw[p], raw[p + 1]
        p += 2
        ref_count = d1 & 0b111
        exotic = bool(d1 & 0b1000)
        data_len = (d2 >> 1) + (d2 & 1)
        data = raw[p : p + data_len]
        p += data_len
        # An odd d2 means the last byte is bit-padded: a 1 bit then zeroes.
        bit_length = data_len * 8
        if d2 & 1 and data:
            padding = data[-1]
            bit_length -= (padding & -padding).bit_length() if padding else 8
        indices = [take_int(ref_size) for _ in range(ref_count)]
        raw_cells.append((Cell(data=data, bit_length=bit_length, exotic=exotic), indices))

    if has_crc:
        p += 4

    for cell, indices in raw_cells:
        cell.refs = [raw_cells[i][0] for i in indices]

    if not roots:
        raise ValueError("bag of cells has no roots")
    return raw_cells[roots[0]][0]


def from_base64(b64: str) -> Cell:
    import base64

    return deserialize(base64.b64decode(b64))
