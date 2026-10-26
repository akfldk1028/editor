"""Bounded split-ZIP reading, reused from the verified NGII receipt auditor."""
from pathlib import Path
import struct
import zlib
import shutil

class MultiDiskReader:
    """Sequential reader across split ZIP disks (.z01, .z02, ..., .zip)."""

    def __init__(self, disk_paths: list[Path]):
        self.disk_paths = disk_paths
        self.disk_sizes = [p.stat().st_size for p in disk_paths]

    def read_span(self, start_disk: int, start_offset: int, length: int) -> bytes:
        out = bytearray()
        disk = start_disk
        offset = start_offset
        remaining = length
        while remaining > 0:
            if disk >= len(self.disk_paths):
                raise EOFError("Split archive ended before requested span finished")
            avail = self.disk_sizes[disk] - offset
            if avail <= 0:
                disk += 1
                offset = 0
                continue
            take = min(remaining, avail)
            with self.disk_paths[disk].open("rb") as f:
                f.seek(offset)
                chunk = f.read(take)
            if len(chunk) != take:
                raise IOError(f"Short read on {self.disk_paths[disk]}")
            out.extend(chunk)
            remaining -= take
            offset += take
            if offset >= self.disk_sizes[disk]:
                disk += 1
                offset = 0
        return bytes(out)

    def iter_span(self, start_disk: int, start_offset: int, length: int, chunk_size: int = 4 * 1024 * 1024):
        disk = start_disk
        offset = start_offset
        remaining = length
        while remaining > 0:
            if disk >= len(self.disk_paths):
                raise EOFError("Split archive ended before compressed stream finished")
            avail = self.disk_sizes[disk] - offset
            if avail <= 0:
                disk += 1
                offset = 0
                continue
            with self.disk_paths[disk].open("rb") as f:
                f.seek(offset)
                while remaining > 0 and offset < self.disk_sizes[disk]:
                    take = min(remaining, chunk_size, self.disk_sizes[disk] - offset)
                    chunk = f.read(take)
                    if not chunk:
                        break
                    yield chunk
                    remaining -= len(chunk)
                    offset += len(chunk)
            if offset >= self.disk_sizes[disk]:
                disk += 1
                offset = 0


def advance_position(disk_sizes: list[int], disk: int, offset: int, delta: int) -> tuple[int, int]:
    rem = delta
    while rem > 0:
        avail = disk_sizes[disk] - offset
        if rem < avail:
            return disk, offset + rem
        rem -= avail
        disk += 1
        offset = 0
    return disk, offset


def stage_members(disks, output, wanted, reserve_bytes):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    reader = MultiDiskReader(disks)
    with disks[-1].open('rb') as f:
        f.seek(max(0, disks[-1].stat().st_size - 65557))
        tail = f.read()
    pos = tail.rfind(b'PK\x05\x06')
    if pos < 0:
        raise ValueError('Missing ZIP EOCD')
    disk, cd_disk, _, count, size, offset, _ = struct.unpack('<4H2LH', tail[pos+4:pos+22])
    if disk + 1 != len(disks):
        raise ValueError('Split ZIP disk count mismatch')
    directory = reader.read_span(cd_disk, offset, size)
    pos = 0
    found = set()
    for _ in range(count):
        values = struct.unpack('<4s6H3L5H2L', directory[pos:pos+46])
        sig, _, _, flags, method, _, _, crc, compressed, expanded, nl, el, cl, start_disk, _, _, local = values
        if sig != b'PK\x01\x02' or flags & 1:
            raise ValueError('Invalid or encrypted ZIP entry')
        name = directory[pos+46:pos+46+nl].decode('utf-8' if flags & 0x800 else 'cp949')
        pos += 46 + nl + el + cl
        if name not in wanted:
            continue
        target = (output / name).resolve()
        if not target.is_relative_to(output):
            raise ValueError('Unsafe ZIP member path')
        if shutil.disk_usage(output).free < reserve_bytes + expanded:
            raise RuntimeError('20 GiB storage reserve before extraction')
        header = reader.read_span(start_disk, local, 30)
        if header[:4] != b'PK\x03\x04' or method not in (0, 8):
            raise ValueError('Unsupported ZIP member')
        fn, extra = struct.unpack('<2H', header[26:30])
        ds, off = advance_position(reader.disk_sizes, start_disk, local, 30+fn+extra)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(target.suffix+'.partial')
        decoder = zlib.decompressobj(-15) if method == 8 else None
        checksum = actual = 0
        with temp.open('wb') as stream:
            for chunk in reader.iter_span(ds, off, compressed, chunk_size=65536):
                data = decoder.decompress(chunk) if decoder else chunk
                stream.write(data); checksum = zlib.crc32(data, checksum); actual += len(data)
            if decoder:
                data = decoder.flush(); stream.write(data); checksum = zlib.crc32(data, checksum); actual += len(data)
        if actual != expanded or checksum & 0xffffffff != crc:
            raise ValueError('Extracted member CRC/size mismatch')
        temp.replace(target)
        found.add(name)
    if found != set(wanted):
        raise ValueError('Required shapefile members absent')

