"""Wire encoding adapted from SaintMocap Operator V5 by Hysaint.

Python UE UDP Messaging v17 / Live Link v2. No Unreal executable required.
Static data are periodically repeated over UDP; this is experimental transport.
"""
import datetime
import socket
import struct
import time

UDP_MESSAGING_TRANSPORT_PROTOCOL_VERSION = 17
MCAST_GRP = '230.0.0.1'
MCAST_PORT = 6666

class EUdpMessageSegments:
    Bye=3
    Data=4
    Hello=5
    Ping=9
    Pong=10

class Float32:
    def __init__(self, val): self.val = float(val)

def pack_fstring(s):
    if not s:
        return struct.pack("<i", 0)
    if not s.isascii():
        encoded = s.encode('utf-16-le') + b'\x00\x00'
        return struct.pack('<i', -len(encoded)//2) + encoded
    encoded = s.encode('utf-8') + b'\x00'
    length = len(encoded)
    return struct.pack("<i", length) + encoded


def unpack_fstring(data, offset):
    length, = struct.unpack_from("<i", data, offset)
    offset += 4
    if length == 0:
        return "", offset
    elif length > 0:
        s = data[offset : offset + length - 1].decode('utf-8')
        return s, offset + length
    else:
        abs_len = abs(length) * 2
        s = data[offset : offset + abs_len - 2].decode('utf-16-le')
        return s, offset + abs_len


def pack_fname(s):
    return pack_fstring(s)


def unpack_fname(data, offset):
    return unpack_fstring(data, offset)


def unpack_guid(data, offset):
    return data[offset : offset + 16], offset + 16


def guid_to_cbor(g_bytes, message_format=4):
    a, b, c, d = struct.unpack(">4I", g_bytes)
    if message_format == 1:
        a = struct.unpack("<I", struct.pack(">I", a))[0]
        b = struct.unpack("<I", struct.pack(">I", b))[0]
        c = struct.unpack("<I", struct.pack(">I", c))[0]
        d = struct.unpack("<I", struct.pack(">I", d))[0]
    return {"A": a, "B": b, "C": c, "D": d}


def serialize_cbor_custom(val, message_format=4):
    if isinstance(val, Float32):
        fmt = "<f" if message_format == 1 else ">f"
        return bytes([0xfa]) + struct.pack(fmt, val.val)
    elif val is None:
        return b'\xf6'
    elif isinstance(val, bool):
        return b'\xf5' if val else b'\xf4'
    elif isinstance(val, int):
        if val >= 0:
            if val < 24:
                return bytes([val])
            elif val < 256:
                return bytes([0x18, val])
            elif val < 65536:
                fmt = "<H" if message_format == 1 else ">H"
                return bytes([0x19]) + struct.pack(fmt, val)
            elif val < 4294967296:
                fmt = "<I" if message_format == 1 else ">I"
                return bytes([0x1a]) + struct.pack(fmt, val)
            else:
                fmt = "<Q" if message_format == 1 else ">Q"
                return bytes([0x1b]) + struct.pack(fmt, val)
        else:
            uval = -1 - val
            if uval < 24:
                return bytes([0x20 + uval])
            elif uval < 256:
                return bytes([0x38, uval])
            elif uval < 65536:
                fmt = "<H" if message_format == 1 else ">H"
                return bytes([0x39]) + struct.pack(fmt, uval)
            elif uval < 4294967296:
                fmt = "<I" if message_format == 1 else ">I"
                return bytes([0x3a]) + struct.pack(fmt, uval)
            else:
                fmt = "<Q" if message_format == 1 else ">Q"
                return bytes([0x3b]) + struct.pack(fmt, uval)
    elif isinstance(val, float):
        fmt = "<d" if message_format == 1 else ">d"
        return bytes([0xfb]) + struct.pack(fmt, val)
    elif isinstance(val, str):
        b_str = val.encode('utf-8')
        L = len(b_str)
        if L < 24:
            return bytes([0x60 + L]) + b_str
        elif L < 256:
            return bytes([0x78, L]) + b_str
        elif L < 65536:
            fmt = "<H" if message_format == 1 else ">H"
            return bytes([0x79]) + struct.pack(fmt, L) + b_str
        else:
            fmt = "<I" if message_format == 1 else ">I"
            return bytes([0x7a]) + struct.pack(fmt, L) + b_str
    elif isinstance(val, (list, tuple)):
        L = len(val)
        if L < 24:
            header = bytes([0x80 + L])
        elif L < 256:
            header = bytes([0x98, L])
        elif L < 65536:
            fmt = "<H" if message_format == 1 else ">H"
            header = bytes([0x99]) + struct.pack(fmt, L)
        else:
            fmt = "<I" if message_format == 1 else ">I"
            header = bytes([0x9a]) + struct.pack(fmt, L)
        body = bytearray()
        for item in val:
            body.extend(serialize_cbor_custom(item, message_format))
        return header + body
    elif isinstance(val, dict):
        L = len(val)
        if L < 24:
            header = bytes([0xa0 + L])
        elif L < 256:
            header = bytes([0xb8, L])
        elif L < 65536:
            fmt = "<H" if message_format == 1 else ">H"
            header = bytes([0xb9]) + struct.pack(fmt, L)
        else:
            fmt = "<I" if message_format == 1 else ">I"
            header = bytes([0xba]) + struct.pack(fmt, L)
        body = bytearray()
        for k, v in val.items():
            body.extend(serialize_cbor_custom(k, message_format))
            body.extend(serialize_cbor_custom(v, message_format))
        return header + body
    raise TypeError(f"Unsupported type: {type(val)}")


def pack_top_level_asset_path(package, asset):
    return pack_fname(package) + pack_fname(asset)


def unpack_top_level_asset_path(data, offset):
    package, offset = unpack_fname(data, offset)
    asset, offset = unpack_fname(data, offset)
    return (package, asset), offset


def datetime_to_ticks(dt):
    days = dt.toordinal() - 1
    seconds_in_day = dt.hour * 3600 + dt.minute * 60 + dt.second
    ticks = (days * 86400 + seconds_in_day) * 10000000 + dt.microsecond * 10
    return ticks


def pack_datetime(dt):
    ticks = datetime_to_ticks(dt)
    return struct.pack("<q", ticks)


def build_header(recipient_guid, sender_guid, segment_type):
    header = bytearray()
    header.append(UDP_MESSAGING_TRANSPORT_PROTOCOL_VERSION)
    header.extend(recipient_guid)
    header.extend(sender_guid)
    header.append(segment_type)
    return header


def unpack_header(data):
    if len(data) < 34:
        return None
    proto_ver = data[0]
    recip, offset = unpack_guid(data, 1)
    sender, offset = unpack_guid(data, offset)
    segment_type = data[offset]
    return {
        "ProtocolVersion": proto_ver,
        "RecipientNodeId": recip,
        "SenderNodeId": sender,
        "SegmentType": segment_type
    }, offset + 1


def parse_data_chunk(data, offset):
    message_id, = struct.unpack_from("<i", data, offset)
    message_size, = struct.unpack_from("<q", data, offset + 4)
    message_flags, = struct.unpack_from("<I", data, offset + 12)
    segment_number, = struct.unpack_from("<I", data, offset + 16)
    segment_offset, = struct.unpack_from("<Q", data, offset + 20)
    total_segments, = struct.unpack_from("<I", data, offset + 28)
    sequence, = struct.unpack_from("<Q", data, offset + 32)
    data_len, = struct.unpack_from("<i", data, offset + 40)
    offset += 44
    payload = data[offset : offset + data_len]
    return {
        "MessageId": message_id,
        "MessageSize": message_size,
        "MessageFlags": message_flags,
        "SegmentNumber": segment_number,
        "SegmentOffset": segment_offset,
        "TotalSegments": total_segments,
        "Sequence": sequence,
        "Payload": payload
    }, offset + data_len


def cbor_to_guid(cbor_dict, message_format=4):
    if not isinstance(cbor_dict, dict):
        return bytearray(16)
    a = cbor_dict.get("A", 0) & 0xffffffff
    b = cbor_dict.get("B", 0) & 0xffffffff
    c = cbor_dict.get("C", 0) & 0xffffffff
    d = cbor_dict.get("D", 0) & 0xffffffff
    if message_format == 1:
        # Swap bytes back because cbor2 loads little-endian values as big-endian
        a = struct.unpack(">I", struct.pack("<I", a))[0]
        b = struct.unpack(">I", struct.pack("<I", b))[0]
        c = struct.unpack(">I", struct.pack("<I", c))[0]
        d = struct.unpack(">I", struct.pack("<I", d))[0]
    return struct.pack(">4I", a, b, c, d)


class WireSender:
    def build_live_link_pong_message(self, message_id, poll_request_guid, recipient_node_id, recipient_msg_address=None, message_format=4):
        package = "/Script/LiveLinkMessageBusFramework"
        asset = "LiveLinkPongMessage"
        cbor_body = serialize_cbor_custom({
            "ProviderName": "RGB MoCap Python (SaintMocap)",
            "MachineName": socket.gethostname(),
            "PollRequest": guid_to_cbor(poll_request_guid, message_format),
            "LiveLinkVersion": 2
        }, message_format)
        # Address Pong to the specific UE LiveLink message address that sent the Ping
        return self.wrap_cbor_payload(
            message_id, package, asset, cbor_body,
            recipient_node_id, recipient_msg_address=recipient_msg_address,
            message_format=message_format
        )


    def wrap_cbor_payload(self, message_id, package, asset, cbor_body, recipient_node_id, recipient_msg_address=None, is_reliable=False, message_format=4):
        payload = bytearray()
        payload.extend(pack_top_level_asset_path(package, asset))
        payload.extend(self.msg_address) # Sender Address
        
        if recipient_msg_address:
            payload.extend(struct.pack("<i", 1)) # Recipients length = 1
            payload.extend(recipient_msg_address)
        else:
            payload.extend(struct.pack("<i", 0)) # Recipients length = 0
            
        payload.append(2) # Scope = Network
        payload.extend(struct.pack("<I", 1 if is_reliable else 0)) # Flags
        payload.extend(pack_datetime(datetime.datetime.now(datetime.timezone.utc))) # TimeSent
        payload.extend(pack_datetime(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1))) # Expiration
        payload.extend(struct.pack("<i", 0)) # Annotations length = 0
        payload.append(message_format) # Format byte!
        payload.extend(cbor_body)
        
        # FDataChunk
        chunk = bytearray()
        chunk.extend(struct.pack("<i", message_id))
        chunk.extend(struct.pack("<q", len(payload)))
        chunk.extend(struct.pack("<I", 1 if is_reliable else 0)) # MessageFlags
        chunk.extend(struct.pack("<I", 0)) # SegmentNumber = 0
        chunk.extend(struct.pack("<Q", 0)) # SegmentOffset = 0
        chunk.extend(struct.pack("<I", 1)) # TotalSegments = 1
        chunk.extend(struct.pack("<Q", 0)) # Sequence = 0
        chunk.extend(struct.pack("<i", len(payload)))
        chunk.extend(payload)
        
        # Final Packet
        packet = bytearray()
        packet.extend(build_header(recipient_node_id, self.node_guid, EUdpMessageSegments.Data))
        packet.extend(chunk)
        return packet


    def send_segmented_payload(self, payload, is_reliable, recipient_node_id, recipient_addr):
        max_segment_size = 1024  # Under MTU (1500) including all network and wrapper headers
        total_size = len(payload)
        total_segments = (total_size + max_segment_size - 1) // max_segment_size
        if total_segments == 0:
            total_segments = 1
            
        message_id = self.message_id_counter
        self.message_id_counter += 1
        
        for seg_idx in range(total_segments):
            seg_offset = seg_idx * max_segment_size
            seg_len = min(max_segment_size, total_size - seg_offset)
            seg_data = payload[seg_offset : seg_offset + seg_len]
            
            chunk = bytearray()
            chunk.extend(struct.pack("<i", message_id))
            chunk.extend(struct.pack("<q", total_size))
            chunk.extend(struct.pack("<I", 1 if is_reliable else 0)) # MessageFlags
            chunk.extend(struct.pack("<I", seg_idx)) # SegmentNumber
            chunk.extend(struct.pack("<Q", seg_offset)) # SegmentOffset
            chunk.extend(struct.pack("<I", total_segments)) # TotalSegments
            chunk.extend(struct.pack("<Q", 0)) # Sequence
            chunk.extend(struct.pack("<i", seg_len)) # DataLen
            chunk.extend(seg_data)
            
            packet = bytearray()
            packet.extend(build_header(recipient_node_id, self.node_guid, EUdpMessageSegments.Data))
            packet.extend(chunk)
            self.unicast_sock.sendto(packet, recipient_addr)


    def send_subject_static_skeleton(self, subject_name, bone_names, bone_parents, client, properties=None):
        remap = self.subject_bone_remaps.get(subject_name, {})
        if "bone_name_map" in remap:
            remap = remap["bone_name_map"]
        mapped_bone_names = [remap.get(name, name) for name in bone_names]
        
        package = "/Script/LiveLinkInterface"
        asset = "LiveLinkSkeletonStaticData"
        message_format = client.get("message_format", 4)
        # BoneNames must be plain strings in CBOR, NOT packed bytes
        cbor_body = serialize_cbor_custom({
            "PropertyNames": properties or [],
            "BoneNames": mapped_bone_names,
            "BoneParents": bone_parents
        }, message_format)
        
        # Build payload with subject annotation
        payload = bytearray()
        payload.extend(pack_top_level_asset_path(package, asset))
        payload.extend(self.msg_address) # Sender Address
        payload.extend(struct.pack("<i", 1)) # Recipients length = 1
        payload.extend(client["msg_address"])
        payload.append(2) # Scope = Network
        payload.extend(struct.pack("<I", 0)) # Periodically refreshed static data
        payload.extend(pack_datetime(datetime.datetime.now(datetime.timezone.utc))) # TimeSent
        payload.extend(pack_datetime(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1))) # Expiration
        
        # Annotations (SubjectName, Role)
        payload.extend(struct.pack("<i", 2)) # Annotations length = 2
        payload.extend(pack_fname("SubjectName") + pack_fstring(subject_name))
        payload.extend(pack_fname("Role") + pack_fstring("LiveLinkAnimationRole"))
        
        payload.append(message_format) # Format byte
        payload.extend(cbor_body)
        
        self.send_segmented_payload(payload, is_reliable=False, recipient_node_id=client["node_guid"], recipient_addr=client["addr"])


    def send_subject_frame_skeleton(self, subject_name, bone_transforms, bone_parents, bone_names, transformed_frame, client, property_values=None):
        package = "/Script/LiveLinkInterface"
        asset = "LiveLinkAnimationFrameData"
        message_format = client.get("message_format", 4)
        
        # Find the skeleton in transformed_frame to read its source_type dynamically
        skeleton = transformed_frame.skeletons.get(subject_name) or transformed_frame.skeletons.get(subject_name + "_std")
        skeleton_source = getattr(skeleton, "source_type", "cortex") if skeleton else "cortex"
        is_cortex = (skeleton_source in ("cortex", "optitrack", "natnet"))

        cbor_transforms = []
        for idx, (px, py, pz, qx, qy, qz, qw) in enumerate(bone_transforms):
            bone_name = bone_names[idx] if idx < len(bone_names) else ""
            parent_idx = bone_parents[idx] if idx < len(bone_parents) else -1
            
            ue_px, ue_py, ue_pz = px, py, pz
            ue_qx, ue_qy, ue_qz, ue_qw = qx, qy, qz, qw

            cbor_transforms.append({
                "Rotation": {"X": ue_qx, "Y": ue_qy, "Z": ue_qz, "W": ue_qw},
                "Translation": {"X": ue_px, "Y": ue_py, "Z": ue_pz},
                "Scale3D": {"X": 1.0, "Y": 1.0, "Z": 1.0}
            })
            
        # Use time.monotonic() for WorldTime.Time.
        # On Windows, both Python's time.monotonic() and UE's FPlatformTime::Seconds()
        # use QueryPerformanceCounter() with the same zero reference (system boot).
        # This means our WorldTime.Time ??UE engine time, so the FClockOffsetEstimatorRamp
        # converges instantly to ~0 offset, GetOffsettedTime() is always increasing,
        # and the 'same time as a previous frame' warnings are eliminated.
        current_time = time.monotonic()
        last_t = self.last_sent_timestamp_by_subject.get(subject_name, 0.0)
        if current_time <= last_t:
            current_time = last_t + 0.001  # Guarantee strict monotonic increase
        self.last_sent_timestamp_by_subject[subject_name] = current_time

        cbor_body = serialize_cbor_custom({
            "WorldTime": {"Time": current_time, "Offset": 0.0},
            "MetaData": {
                "StringMetaData": {}
            },
            "PropertyValues": property_values or [],
            "Transforms": cbor_transforms
        }, message_format)
        
        payload = bytearray()
        payload.extend(pack_top_level_asset_path(package, asset))
        payload.extend(self.msg_address) # Sender Address
        payload.extend(struct.pack("<i", 1)) # Recipients length = 1
        payload.extend(client["msg_address"])
        payload.append(2) # Scope = Network
        payload.extend(struct.pack("<I", 0)) # Flags = 0 (Unreliable frame data)
        payload.extend(pack_datetime(datetime.datetime.now(datetime.timezone.utc))) # TimeSent
        payload.extend(pack_datetime(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1))) # Expiration
        
        # Annotations (SubjectName)
        payload.extend(struct.pack("<i", 1)) # Annotations length = 1
        payload.extend(pack_fname("SubjectName") + pack_fstring(subject_name))
        
        payload.append(message_format) # Format byte
        payload.extend(cbor_body)
        
        self.send_segmented_payload(payload, is_reliable=False, recipient_node_id=client["node_guid"], recipient_addr=client["addr"])


