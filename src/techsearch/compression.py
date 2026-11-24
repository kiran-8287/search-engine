"""Three byte-addressable encodings of the same positional posting lists."""
from __future__ import annotations

import struct
from itertools import chain, islice

CODECS = ("uint32", "vb", "gamma")


def gaps(values):
    """Encode sorted document IDs as positive gaps, starting from -1."""
    previous_id = -1
    for document_id in values:
        if document_id <= previous_id:
            raise ValueError("Document IDs must be nonnegative and strictly increasing")
        yield document_id - previous_id
        previous_id = document_id


def encode(values, codec):
    """Return an encoded integer stream and its meaningful bit count."""
    if codec == "uint32":
        values = list(values)
        return struct.pack(f"<{len(values)}I", *values), 32 * len(values)
    if codec == "vb":
        return encode_variable_byte(values)
    if codec == "gamma":
        return encode_gamma(values)
    raise ValueError(f"Unknown codec {codec}")


def encode_variable_byte(values):
    """Store seven bits per byte, with the high bit marking the last byte."""
    output = bytearray()
    for value in values:
        if value < 0:
            raise ValueError("Integers must be nonnegative")
        while value >= 128:
            output.append(value & 127)
            value >>= 7
        output.append(value | 128)
    return bytes(output), 8 * len(output)


def encode_gamma(values):
    """Store gamma codes for value + 1 so zero can be represented."""
    output = bytearray()
    buffer = pending_bits = total_bits = 0
    for value in values:
        if value < 0:
            raise ValueError("Integers must be nonnegative")
        positive = value + 1
        width = 2 * positive.bit_length() - 1
        # Each gamma code has a zero prefix followed by the binary value.
        buffer = (buffer << width) | positive
        pending_bits += width
        total_bits += width
        while pending_bits >= 8:
            pending_bits -= 8
            output.append(buffer >> pending_bits)
            buffer &= (1 << pending_bits) - 1
    if pending_bits:
        output.append(buffer << (8 - pending_bits))
    return bytes(output), total_bits


def decode(payload, bits, codec):
    """Read integers from a posting payload and reject invalid lengths."""
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
        yield from decode_variable_byte(payload)
        return
    if codec != "gamma":
        raise ValueError(f"Unknown codec {codec}")
    if bits % 8 and payload[-1] & ((1 << (8 - bits % 8)) - 1):
        raise ValueError("Nonzero gamma padding")
    yield from decode_gamma(payload, bits)


def decode_variable_byte(payload):
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


def decode_gamma(payload, bits):
    """Use the zero prefix length to read the rest of each binary value."""
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
    """Flatten document, field and position records in their on-disk order."""
    def integers():
        yield len(postings)
        doc_gaps = gaps(postings)
        for (document_id, fields), gap in zip(postings.items(), doc_gaps):
            yield document_id if codec == "uint32" else gap
            yield len(fields)
            for field, occurrences in fields.items():
                yield field
                yield len(occurrences)
                yield from chain.from_iterable(occurrences)
    return encode(integers(), codec)


def unpack_postings(payload, bits, codec):
    """Rebuild keyed posting lists, including each five-value position record."""
    values = iter(decode(payload, bits, codec))
    result = {}
    previous_id = -1
    try:
        document_count = next(values)
        for _ in range(document_count):
            token = next(values)
            document_id = token if codec == "uint32" else previous_id + token
            if document_id <= previous_id:
                raise ValueError("Invalid posting document order")
            previous_id = document_id
            fields = {}
            field_count = next(values)
            for _ in range(field_count):
                field = next(values)
                frequency = next(values)
                positions = []
                for _ in range(frequency):
                    position = tuple(islice(values, 5))
                    if len(position) != 5:
                        raise ValueError("Truncated posting list")
                    positions.append(position)
                fields[field] = positions
            result[document_id] = fields
    except StopIteration as error:
        raise ValueError("Truncated posting list") from error
    if next(values, None) is not None:
        raise ValueError("Trailing posting integers")
    return result
