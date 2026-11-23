"""Numerical and real localhost wire tests; no UE or model inference required."""
from pathlib import Path
import ast
import importlib.util
import socket
import struct
import sys
import time
import types
import unittest
import uuid

import numpy as np

ROOT=Path(__file__).parents[1]
sys.path.insert(0,str(ROOT))
from mocap.bone_stream import StreamRig, Y_TO_Z
from mocap.python_livelink import (PythonLiveLink,decode_cbor,envelope,prepared_snapshot,live_snapshot)
from mocap.python_livelink_rig import local_transforms, BLENDER_TO_UE
from mocap.python_livelink_wire import (WireSender,build_header,parse_data_chunk,serialize_cbor_custom,
    guid_to_cbor,pack_fstring,unpack_fstring,EUdpMessageSegments as Seg)
from integrate_stream import integrate
from test_pear_vmc import fixture,PARENTS,rotation,axis_rotation


def rig_fixture(count=52):
    names=['Hips']+[f'Bone_{i}' for i in range(1,count)]
    parents=[-1]+list(range(count-1))
    bind=np.tile(np.eye(3),(count,1,1)); heads=np.zeros((count,3))
    heads[:,1]=np.arange(count)*.01
    rig=StreamRig(names,parents,heads,bind,bind,np.full(count,.01))
    world=np.tile(np.eye(4),(count,1,1)); world[:,:3,3]=heads
    world[0,:3,3]=[.3,1.,2.]
    return rig,world


class Peer(WireSender):
    def __init__(self):
        self.node_guid=uuid.uuid4().bytes; self.msg_address=uuid.uuid4().bytes
        self.sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); self.sock.bind(('127.0.0.1',0))
        self.sock.settimeout(.05); self.counter=1; self.chunks={}
    def send(self,sender,name,body,fmt=4):
        packet=self.wrap_cbor_payload(self.counter,'/Script/LiveLinkMessageBusFramework',name,
            serialize_cbor_custom(body,fmt),sender.node_guid,sender.msg_address,message_format=fmt)
        self.counter+=1; self.sock.sendto(packet,('127.0.0.1',sender.port))
    def wait(self,kind,timeout=2):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            try: raw,_=self.sock.recvfrom(65535)
            except socket.timeout: continue
            if len(raw)<78 or raw[33]!=Seg.Data: continue
            self.assert_size(raw)
            chunk,_=parse_data_chunk(raw,34)
            mid=chunk['MessageId']; pieces=self.chunks.setdefault(mid,{})
            pieces[chunk['SegmentNumber']]=chunk['Payload']
            if len(pieces)!=chunk['TotalSegments']: continue
            payload=b''.join(pieces[i] for i in range(chunk['TotalSegments']))
            del self.chunks[mid]
            name,_,fmt,annotations,body=envelope(payload)
            if name==kind: return annotations,decode_cbor(body,fmt)
        raise AssertionError('No '+kind+' received')
    def assert_size(self,packet):
        if len(packet)>1400: raise AssertionError('UDP datagram exceeded MTU budget')
    def close(self): self.sock.close()


class LiveLinkTests(unittest.TestCase):
    def test_cbor_formats_and_unicode_fstrings(self):
        for fmt in (1,4):
            body={'PollRequest':guid_to_cbor(uuid.uuid4().bytes,fmt),'name':'����','test':[1,-3,2.5,True,None]}
            self.assertEqual(decode_cbor(serialize_cbor_custom(body,fmt),fmt),body)
        for name in ('Actor','�����','test??'):
            raw=pack_fstring(name); self.assertEqual(unpack_fstring(raw,0),(name,len(raw)))
        for raw in (b'\x9f',b'\x1a\xff',b'\x81'*10):
            with self.assertRaises(ValueError): decode_cbor(raw)

    def test_prepared_52_and_77_bone_rigs_reconstruct(self):
        for count in (52,77):
            rig,world=rig_fixture(count); scene=np.eye(4)
            scene[:3,:3]=axis_rotation(1,.6); scene[:3,3]=[2.,.2,-3.]
            before=world.copy()
            subject,key,names,parents,poses=prepared_snapshot((('a'*64,'����',rig,0,world,scene),))[0]
            self.assertEqual(len(names),count); self.assertIn('����',subject)
            points=[]; rots=[]
            for parent,pose in zip(parents,poses):
                p=np.array(pose[:3]); r=rotation(pose[3:])
                points.append(p if parent<0 else points[parent]+rots[parent]@p)
                rots.append(r if parent<0 else rots[parent]@r)
            matrices=np.frombuffer(rig.pose(world,scene),dtype='<f4').reshape(-1,3,4)
            expected=(BLENDER_TO_UE@matrices[:,:,3,None])[...,0]*100
            np.testing.assert_allclose(points,expected,atol=1e-8)
            np.testing.assert_array_equal(before,world)
            world[0,0,0]=np.nan
            with self.assertRaises(ValueError): prepared_snapshot((('a'*64,'Actor',rig,0,world,None),))

    def test_live_pear_alignment_equivalence(self):
        pose,_,_=fixture(); parents=PARENTS
        raw=live_snapshot(pose,parents,False)
        from mocap.pear_vmc import DISPLAY
        adjusted={'joints':pose['joints']@DISPLAY.T,'rotations':DISPLAY@pose['rotations']}
        other=live_snapshot(adjusted,parents,True)
        self.assertEqual(len(raw[0][2]),52)
        np.testing.assert_allclose(raw[0][4],other[0][4],atol=1e-9)

    def test_real_udp_discovery_connect_frames_and_removal(self):
        self.require_loopback()
        sender=PythonLiveLink(); peer=Peer()
        try:
            for fmt in (1,4):
                poll=uuid.uuid4().bytes
                peer.send(sender,'LiveLinkPingMessage',{'PollRequest':guid_to_cbor(poll,fmt),'LiveLinkVersion':2},fmt)
                _,pong=peer.wait('LiveLinkPongMessage')
                self.assertEqual(pong['ProviderName'],'RGB MoCap Python (SaintMocap)')
            peer.send(sender,'LiveLinkConnectMessage',{},4)
            rig,world=rig_fixture(77)
            sender.publish((('a'*64,'Actor',rig,0,world,None),))
            ann,static=peer.wait('LiveLinkSkeletonStaticData')
            self.assertEqual(len(static['BoneNames']),77)
            _,first=peer.wait('LiveLinkAnimationFrameData')
            self.assertEqual(len(first['Transforms']),77)
            # Drain before changing the playhead to avoid mistaking a heartbeat
            # for the requested new position.
            world[:,:3,3]+=[1.,0.,0.]
            sender.publish((('a'*64,'Actor',rig,1,world,None),))
            end=time.monotonic()+2
            while True:
                _,second=peer.wait('LiveLinkAnimationFrameData')
                if abs(second['Transforms'][0]['Translation']['X']-first['Transforms'][0]['Translation']['X'])>99: break
                self.assertLess(time.monotonic(),end)
            sender.publish(())
            _,clear=peer.wait('LiveLinkClearSubject')
            self.assertEqual(clear['SubjectName'],ann['SubjectName'])
            self.assertTrue(sender.connected)
        finally:
            sender.close(); sender.thread.join(2); peer.close()
        self.assertFalse(sender.thread.is_alive()); self.assertFalse(sender.connected)

    def test_invalid_start_and_live_loss_timeout(self):
        for args in (('0.0.0.0',),('127.0.0.1',-1),('127.0.0.1',0,'host.invalid:6666')):
            with self.assertRaises(ValueError): PythonLiveLink(*args)
        self.require_loopback()
        sender=PythonLiveLink(); peer=Peer()
        try:
            peer.send(sender,'LiveLinkConnectMessage',{})
            pose,_,_=fixture(); sender.submit_live(pose,PARENTS)
            peer.wait('LiveLinkAnimationFrameData')
            peer.wait('LiveLinkClearSubject',timeout=2)
            self.assertEqual(sender.subjects,0)
        finally:
            sender.close(); sender.thread.join(2); peer.close()

    def require_loopback(self):
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as receiver, socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as tx:
            receiver.bind(('127.0.0.1',0)); receiver.settimeout(.1)
            tx.sendto(b'probe',receiver.getsockname())
            try: self.assertEqual(receiver.recvfrom(16)[0],b'probe')
            except socket.timeout: self.skipTest('Environment blocks localhost UDP, including a standalone probe')

    def test_wire_replay_discovery_frames_clear_and_endian(self):
        class Capture:
            def __init__(self): self.packets=[]
            def sendto(self,packet,addr): self.packets.append(bytes(packet))
        sender=PythonLiveLink(); sender.close(); sender.thread.join(2)
        sender.unicast_sock=Capture()
        peer=Peer()
        try:
            for fmt in (1,4):
                poll=uuid.uuid4().bytes
                packet=peer.wrap_cbor_payload(1,'/Script/LiveLinkMessageBusFramework','LiveLinkPingMessage',
                    serialize_cbor_custom({'PollRequest':guid_to_cbor(poll,fmt),'LiveLinkVersion':2},fmt),
                    sender.node_guid,sender.msg_address,message_format=fmt)
                sender._receive(bytes(packet),peer.sock.getsockname())
                reply=sender.unicast_sock.packets.pop()
                name,address,mode,_,body=envelope(parse_data_chunk(reply,34)[0]['Payload'])
                self.assertEqual(name,'LiveLinkPongMessage')
                self.assertEqual(decode_cbor(body,mode)['PollRequest'],guid_to_cbor(poll,fmt))
            packet=peer.wrap_cbor_payload(2,'/Script/LiveLinkMessageBusFramework','LiveLinkConnectMessage',
                serialize_cbor_custom({},4),sender.node_guid,sender.msg_address,message_format=4)
            sender._receive(bytes(packet),peer.sock.getsockname())
            self.assertEqual(len(sender.clients),1)
            rig,world=rig_fixture(77)
            poses=prepared_snapshot((('a'*64,'�����',rig,0,world,None),))
            sender._send_poses(poses,time.monotonic())
            groups={}
            for raw in sender.unicast_sock.packets:
                self.assertLessEqual(len(raw),1400)
                chunk,_=parse_data_chunk(raw,34)
                groups.setdefault(chunk['MessageId'],{})[chunk['SegmentNumber']]=chunk['Payload']
            messages={}
            for pieces in groups.values():
                payload=b''.join(pieces[i] for i in range(len(pieces)))
                name,_,fmt,ann,body=envelope(payload); messages[name]=(ann,decode_cbor(body,fmt))
            self.assertEqual(len(messages['LiveLinkSkeletonStaticData'][1]['BoneNames']),77)
            self.assertEqual(len(messages['LiveLinkAnimationFrameData'][1]['Transforms']),77)
            self.assertIn('�����',messages['LiveLinkAnimationFrameData'][0]['SubjectName'])
            sender.unicast_sock.packets.clear(); sender._send_poses((),time.monotonic())
            raw=sender.unicast_sock.packets[-1]
            name,_,fmt,_,body=envelope(parse_data_chunk(raw,34)[0]['Payload'])
            self.assertEqual(name,'LiveLinkClearSubject')
            self.assertEqual(decode_cbor(body,fmt)['SubjectName'],poses[0][0])
            for raw in (b'',b'\x11'*40,packet[:78],b'\xff'*200):
                sender._receive(bytes(raw),peer.sock.getsockname())
        finally: peer.close()

    def test_stream_integration_preserves_upstream_modes(self):
        text=(ROOT/'mocap/stream_ui.py').read_text(encoding='utf8')
        self.assertEqual(integrate(text),text)
        ast.parse(text)
        self.assertIn("['None', 'Blender', 'VMC']",text)
        upstream=ROOT/'_upstream_stream.py'
        if upstream.exists():
            text=integrate(upstream.read_text(encoding='utf8'))
            ast.parse(text)
            self.assertIn("['None', 'Blender', 'Unreal Live Link']",text)
            self.assertIn('UnrealStream(ROOT)',text)
            self.assertIn('Export Reference FBX...',text)

if __name__=='__main__': unittest.main(verbosity=2)
