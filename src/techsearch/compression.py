"""Three byte-addressable encodings of the same positional posting lists."""
from __future__ import annotations

import struct
from itertools import chain

CODECS = ("uint32", "vb", "gamma")


def gaps(values):
    previous = -1
    for value in values:
        if value <= previous:
            raise ValueError("Document IDs must be nonnegative and strictly increasing")
        yield value - previous
        previous = value


def encode(values, codec):
    if codec == "uint32":
        values = list(values)
        return struct.pack(f"<{len(values)}I", *values), 32 * len(values)
    output = bytearray()
    if codec == "vb":
        for value in values:
            if value < 0:
                raise ValueError("Integers must be nonnegative")
            while value >= 128:
                output.append(value & 127)
                value >>= 7
            output.append(value | 128)
        return bytes(output), 8 * len(output)
    if codec != "gamma":
        raise ValueError(f"Unknown codec {codec}")
    accumulator = pending = bits = 0
    for value in values:
        if value < 0:
            raise ValueError("Integers must be nonnegative")
        positive = value + 1
        width = 2 * positive.bit_length() - 1
        accumulator = (accumulator << width) | positive
        pending += width
        bits += width
        while pending >= 8:
            pending -= 8
            output.append(accumulator >> pending)
            accumulator &= (1 << pending) - 1
    if pending:
        output.append(accumulator << (8 - pending))
    return bytes(output), bits


def decode(payload, bits, codec):
    if bits < 0 or (bits + 7) // 8 != len(payload):
        raise ValueError("Invalid posting bit length")
    if codec == "uint32":
        if bits % 32:
            raise ValueError("Truncated uint32")
        yield from (value for (value,) in struct.iter_unpack("<I", payload))
        return
    if codec == "vb":
        if bits % 8:
            raise ValueError("Truncated variable-byte payload")
        value = shift = 0
        for byte in payload:
            value |= (byte & 127) << shift
            if byte & 128:
                yield value
                value = shift = 0
            else:
                shift += 7
                if shift > 35:
                    raise ValueError("Oversized variable-byte integer")
        if shift:
            raise ValueError("Truncated variable-byte integer")
        return
    if codec != "gamma":
        raise ValueError(f"Unknown codec {codec}")
    if bits % 8 and payload[-1] & ((1 << (8 - bits % 8)) - 1):
        raise ValueError("Nonzero gamma padding")
    stream = iter((payload[index // 8] >> (7 - index % 8)) & 1 for index in range(bits))
    try:
        while (first := next(stream, None)) is not None:
            zeros = 0
            while first == 0:
                first = next(stream)
                zeros += 1
                if zeros > 32:
                    raise ValueError("Oversized gamma integer")
            value = 1
            for _ in range(zeros):
                value = (value << 1) | next(stream)
            yield value - 1
    except StopIteration as error:
        raise ValueError("Truncated gamma integer") from error


def pack_postings(postings, codec):
    def integers():
        yield len(postings)
        doc_gaps = gaps(postings)
        for (doc, fields), gap in zip(postings.items(), doc_gaps):
            yield doc if codec == "uint32" else gap
            yield len(fields)
            for field, occurrences in fields.items():
                yield field
                yield len(occurrences)
                yield from chain.from_iterable(occurrences)
    return encode(integers(), codec)


def unpack_postings(payload, bits, codec):
    values = iter(decode(payload, bits, codec))
    result, previous = {}, -1
    try:
        for _ in range(next(values)):
            token = next(values)
            doc = token if codec == "uint32" else token + previous
            if doc <= previous:
                raise ValueError("Invalid posting document order")
            previous = doc
            fields = {}
            for _ in range(next(values)):
                field, frequency = next(values), next(values)
                fields[field] = [tuple(next(values) for _ in range(5)) for _ in range(frequency)]
            result[doc] = fields
    except (StopIteration, RuntimeError) as error:
        raise ValueError("Truncated posting list") from error
    if next(values, None) is not None:
        raise ValueError("Trailing posting integers")
    return result
