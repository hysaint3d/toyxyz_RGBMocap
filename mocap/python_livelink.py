"""Opt-in Python Live Link provider derived from SaintMocap V5.

One worker owns discovery, parsing, conversion and sending. A bounded latest
snapshot replaces queued frames. No models, Qt, cbor2, C++ or UE process imports.
"""
import ipaddress
import re
import select
import socket
import struct
import threading
import time
import uuid
from types import SimpleNamespace

import numpy as np

from .python_livelink_wire import (
    WireSender, MCAST_GRP, MCAST_PORT, EUdpMessageSegments as Seg,
    build_header, unpack_header, parse_data_chunk, unpack_top_level_asset_path,
    unpack_fstring, unpack_fname, cbor_to_guid, pack_fstring, pack_fname,
    pack_top_level_asset_path, pack_datetime, serialize_cbor_custom,
)
from .python_livelink_rig import local_transforms, rig_schema, subject_name
from .bone_stream import Y_TO_Z
from .pear_vmc import DISPLAY, NAMES

TARGET = 'Python Live Link (SaintMocap)'
PROVIDER = 'RGB MoCap Python (SaintMocap)'


def decode_cbor(data, message_format=4):
    """Bounded CBOR subset needed for UE Ping GUIDs, with V5 endian format 1.

    Definite-size primitive arrays/maps only; no tags, objects or indefinite data.
    """
    if len(data) > 65535:
        raise ValueError('Oversized CBOR message')
    offset = 0
    endian = '<' if message_format == 1 else '>'

    def read(size):
        nonlocal offset
        if size < 0 or offset+size > len(data):
            raise ValueError('Truncated CBOR')
        value = data[offset:offset+size]; offset += size
        return value

    def value(depth=0):
        if depth > 8:
            raise ValueError('CBOR nesting limit')
        head = read(1)[0]; major, info = head >> 5, head & 31
        if major == 7:
            if info in (20,21,22): return {20:False,21:True,22:None}[info]
            if info in (26,27): return struct.unpack(endian+('f' if info==26 else 'd'),read(4 if info==26 else 8))[0]
            raise ValueError('Unsupported CBOR primitive')
        if info < 24: size=info
        elif info in (24,25,26,27):
            size=struct.unpack(endian+{24:'B',25:'H',26:'I',27:'Q'}[info],read(1 << (info-24)))[0]
        else: raise ValueError('Indefinite CBOR is unsupported')
        if major == 0: return size
        if major == 1: return -1-size
        if size > 4096: raise ValueError('CBOR item limit')
        if major == 2: return read(size)
        if major == 3: return read(size).decode('utf8')
        if major == 4: return [value(depth+1) for _ in range(size)]
        if major == 5:
            result={}
            for _ in range(size):
                key=value(depth+1); result[key]=value(depth+1)
            return result
        raise ValueError('Unsupported CBOR type')

    result=value()
    if offset != len(data): raise ValueError('Trailing CBOR bytes')
    return result


def envelope(payload):
    """Parse the small single-segment discovery/connect envelope."""
    path, offset = unpack_top_level_asset_path(payload, 0)
    address=bytes(payload[offset:offset+16]); offset+=16
    count=struct.unpack_from('<i',payload,offset)[0]; offset+=4
    if not 0 <= count <= 16: raise ValueError('Recipient limit')
    offset+=count*16+1+4+16
    count=struct.unpack_from('<i',payload,offset)[0]; offset+=4
    if not 0 <= count <= 16: raise ValueError('Annotation limit')
    annotations={}
    for _ in range(count):
        key,offset=unpack_fname(payload,offset)
        annotations[key],offset=unpack_fstring(payload,offset)
    fmt=payload[offset]; offset+=1
    if fmt not in (1,4): raise ValueError('Unsupported UE CBOR format')
    return path[1],address,fmt,annotations,payload[offset:]


def prepared_snapshot(actors):
    result=[]; used=set()
    for actor,name,rig,frame,world,transform in actors:
        subject=subject_name(actor,name)
        if subject.casefold() in used: raise ValueError('Live Link subject names collide')
        used.add(subject.casefold())
        schema=rig_schema(rig)
        matrices=np.frombuffer(rig.pose(world,transform),dtype='<f4').reshape(-1,3,4)
        result.append((subject,schema['rig'],schema['names'],schema['parents'],
                       local_transforms(matrices,schema['parents'])))
    return tuple(result)


def live_snapshot(pose, parents, aligned):
    joints=np.asarray(pose['joints'],dtype=float)[:55].copy()
    rotations=np.asarray(pose['rotations'],dtype=float).copy()
    parents=np.asarray(parents)
    if joints.shape!=(55,3) or rotations.shape!=(55,3,3) or parents.shape!=(55,) or parents.dtype.kind not in 'iu':
        raise ValueError('Invalid live PEAR pose')
    indices=tuple(NAMES); lookup={bone:i for i,bone in enumerate(indices)}
    if parents[0]!=-1 or any(parents[i] not in lookup or parents[i]>=i for i in indices if i):
        raise ValueError('Invalid live PEAR hierarchy')
    if aligned:
        joints=joints@DISPLAY; rotations=DISPLAY.T@rotations
    world=np.concatenate((rotations,joints[...,None]),axis=-1)[list(indices)]
    mapped=[-1 if parents[i]<0 else lookup[int(parents[i])] for i in indices]
    return (('RGBMoCap_PEAR',tuple(mapped),[NAMES[i] for i in indices],mapped,
             local_transforms(Y_TO_Z@world,mapped)),)


class PythonLiveLink(WireSender):
    target=TARGET

    def __init__(self, local_ip='127.0.0.1', local_port=0, static_endpoint=''):
        address=ipaddress.IPv4Address(local_ip.strip())
        if address.is_multicast or address.is_unspecified:
            raise ValueError('Select a concrete local IPv4 interface')
        if not 0 <= int(local_port) <= 65535: raise ValueError('Invalid local UDP port')
        self.static=None
        if static_endpoint.strip():
            host,port=static_endpoint.strip().rsplit(':',1)
            dest=ipaddress.IPv4Address(host)
            if dest.is_multicast or dest.is_unspecified or not 1<=int(port)<=65535:
                raise ValueError('Use a unicast IPv4:port static endpoint')
            self.static=str(dest),int(port)
        self.node_guid=uuid.uuid4().bytes; self.msg_address=uuid.uuid4().bytes
        self.message_id_counter=1; self.subject_bone_remaps={}
        self.last_sent_timestamp_by_subject={}
        self.stop_event=threading.Event(); self.lock=threading.Lock()
        self.latest=None; self.errors=''; self.clients={}; self.connected=False
        self.ready=False; self.frames=0; self.subjects=0; self._live=False
        self.unicast_sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        self.mcast_sock=None
        try:
            self.unicast_sock.bind((str(address),int(local_port)))
            self.port=self.unicast_sock.getsockname()[1]
            self.unicast_sock.setsockopt(socket.IPPROTO_IP,socket.IP_MULTICAST_IF,socket.inet_aton(str(address)))
            self.unicast_sock.setsockopt(socket.IPPROTO_IP,socket.IP_MULTICAST_LOOP,1)
            self.unicast_sock.setblocking(False)
            self.mcast_sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
            self.mcast_sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            self.mcast_sock.bind(('',MCAST_PORT))
            self.mcast_sock.setsockopt(socket.IPPROTO_IP,socket.IP_ADD_MEMBERSHIP,
                                      socket.inet_aton(MCAST_GRP)+socket.inet_aton(str(address)))
            self.mcast_sock.setblocking(False)
        except BaseException:
            self.unicast_sock.close()
            if self.mcast_sock: self.mcast_sock.close()
            raise
        self.thread=threading.Thread(target=self._run,name='Python Live Link',daemon=True)
        self.thread.start()

    def publish(self, actors):
        if len(actors)>128: raise ValueError('Too many Live Link people')
        copied=[]
        for actor,name,rig,frame,world,transform in actors:
            if not 0<len(rig.bones)<=256: raise ValueError('Too many bones')
            copied.append((actor,name,rig,frame,np.array(world,copy=True),
                           None if transform is None else np.array(transform,copy=True)))
        with self.lock: self.latest=('offline',tuple(copied),time.monotonic())

    def submit_live(self,pose,parents=None,aligned=False):
        copied=None if pose is None else (dict(joints=np.array(pose['joints'][:55],copy=True),
            rotations=np.array(pose['rotations'],copy=True)),np.array(parents,copy=True),bool(aligned))
        with self.lock: self.latest=('live',copied,time.monotonic())

    def close(self):
        self.stop_event.set()  # Worker owns socket closure; never wait in Qt.

    def error(self):
        return self.errors or None

    def _control(self,kind,body,client):
        payload=serialize_cbor_custom(body,client['message_format'])
        packet=self.wrap_cbor_payload(self.message_id_counter,'/Script/LiveLinkMessageBusFramework',
            kind,payload,client['node_guid'],client['msg_address'],message_format=client['message_format'])
        self.message_id_counter+=1
        self.unicast_sock.sendto(packet,client['addr'])

    def _receive(self,data,addr):
        if len(data)<34 or data[0]!=17: return
        header,_=unpack_header(data)
        if header['SenderNodeId']==self.node_guid: return
        if header['RecipientNodeId'] not in (bytes(16),self.node_guid): return
        node=bytes(header['SenderNodeId']); kind=header['SegmentType']; now=time.monotonic()
        for client in self.clients.values():
            if client['node_guid']==node and client['addr']==addr: client['seen']=now
        if kind==Seg.Bye:
            self.clients={k:v for k,v in self.clients.items() if v['node_guid']!=node}; return
        if kind==Seg.Ping:
            self.unicast_sock.sendto(build_header(node,self.node_guid,Seg.Pong),addr); return
        if kind!=Seg.Data or len(data)<78: return
        chunk,_=parse_data_chunk(data,34)
        if (chunk['TotalSegments']!=1 or chunk['SegmentNumber']!=0 or chunk['SegmentOffset']!=0
                or chunk['MessageSize']!=len(chunk['Payload']) or chunk['MessageSize']!=len(data)-78): return
        name,address,fmt,_,body=envelope(chunk['Payload'])
        if len(address)!=16: return
        if name=='LiveLinkPingMessage':
            decoded=decode_cbor(body,fmt)
            poll=cbor_to_guid(decoded['PollRequest'],fmt)
            packet=self.build_live_link_pong_message(self.message_id_counter,poll,node,address,fmt)
            self.message_id_counter+=1; self.unicast_sock.sendto(packet,addr)
        elif name=='LiveLinkConnectMessage' and len(self.clients)<16:
            self.clients[address]=dict(node_guid=node,msg_address=address,addr=addr,message_format=fmt,
                                       seen=now,registered={})

    def _send_poses(self,poses,now):
        wanted={p[0] for p in poses}
        empty=SimpleNamespace(skeletons={})
        for client in tuple(self.clients.values()):
            for subject in set(client['registered'])-wanted:
                self._control('LiveLinkClearSubject',{'SubjectName':subject},client)
                del client['registered'][subject]
            for subject,key,names,parents,transforms in poses:
                old=client['registered'].get(subject)
                if old is None or old[0]!=key or now-old[1]>=1.:
                    self.send_subject_static_skeleton(subject,names,parents,client)
                    client['registered'][subject]=(key,now)
                self.send_subject_frame_skeleton(subject,transforms,parents,names,empty,client)
        self.subjects=len(poses)
        for subject in set(self.last_sent_timestamp_by_subject)-wanted:
            del self.last_sent_timestamp_by_subject[subject]
        if poses and self.clients: self.frames+=1

    def _run(self):
        last_hello=0.; last_send=0.; last_heartbeat=0.; processed=None; poses=()
        self.ready=True
        try:
            while not self.stop_event.is_set():
                now=time.monotonic()
                if now-last_hello>=1.:
                    hello=build_header(bytes(16),self.node_guid,Seg.Hello)+self.node_guid
                    self.unicast_sock.sendto(hello,(MCAST_GRP,MCAST_PORT))
                    if self.static: self.unicast_sock.sendto(hello,self.static)
                    last_hello=now
                readable,_,_=select.select([self.unicast_sock,self.mcast_sock],[],[],.02)
                for sock in readable:
                    for _ in range(32):
                        try: data,addr=sock.recvfrom(65535)
                        except BlockingIOError: break
                        try: self._receive(data,addr)
                        except (ValueError,KeyError,TypeError,IndexError,struct.error,UnicodeError): pass
                self.clients={k:v for k,v in self.clients.items() if now-v['seen']<10.}
                self.connected=bool(self.clients)
                if now-last_heartbeat>=1.:
                    for client in self.clients.values():
                        self._control('LiveLinkHeartbeatMessage',{},client)
                    last_heartbeat=now
                with self.lock: latest=self.latest
                if latest is not processed:
                    try:
                        poses=() if latest is None else (prepared_snapshot(latest[1]) if latest[0]=='offline'
                                  else live_snapshot(*latest[1]) if latest[1] is not None else ())
                        self.errors=''
                    except (ValueError,KeyError,TypeError,IndexError,OSError) as exc:
                        poses=(); self.errors=str(exc)
                    processed=latest
                if latest is not None and now-latest[2]>(.75 if latest[0]=='live' else 1.5): poses=()
                if now-last_send>=1/30:
                    self._send_poses(poses,now); last_send=now
        except OSError as exc:
            self.errors=str(exc)
        finally:
            try:
                self._send_poses((),time.monotonic())
                for client in self.clients.values():
                    self.unicast_sock.sendto(build_header(client['node_guid'],self.node_guid,Seg.Bye)+self.node_guid,client['addr'])
            except OSError: pass
            self.clients.clear(); self.connected=False; self.ready=False
            self.unicast_sock.close()
            self.mcast_sock.close()
