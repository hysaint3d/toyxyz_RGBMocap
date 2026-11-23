"""Real UDP output checks for the knee correction; no models or UE required."""
from pathlib import Path
import socket
import sys
import time
import unittest
import numpy as np

ROOT=Path(__file__).parents[1];sys.path.insert(0,str(ROOT))
from mocap.pear_vmc import Sender
from mocap.python_livelink import PythonLiveLink
from mocap.knee_lock import vmc_parents,rotation,leg_indices
from test_pear_vmc import fixture,PARENTS,decode
from test_python_livelink import Peer,rig_fixture


def fk(names,parents,poses):
    points=[];rotations=[]
    for parent,pose in zip(parents,poses):
        p=np.asarray(pose[:3]);r=rotation(pose[3:])
        points.append(p if parent<0 else points[parent]+rotations[parent]@p)
        rotations.append(r if parent<0 else rotations[parent]@r)
    return np.array(points)


class KneeStreamTests(unittest.TestCase):
    def test_vmc_udp_fixed_knees_and_release(self):
        receiver=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        receiver.bind(('127.0.0.1',0));receiver.settimeout(.5)
        sender=Sender('127.0.0.1',receiver.getsockname()[1])
        def bones():
            result={};end=time.monotonic()+2
            while time.monotonic()<end:
                for addr,tags,values in decode(receiver.recvfrom(2048)[0]):
                    if addr=='/VMC/Ext/Bone/Pos':result[values[0]]=values[1:]
                    if addr=='/VMC/Ext/T' and len(result)==52:return result
            raise AssertionError(sender.error or 'No complete VMC pose')
        try:
            sender.configure_knees(True,True,0,'pear')
            pose,_,_=fixture();sender.submit(pose,PARENTS)
            first=bones(); names=list(first);parents=vmc_parents(names)
            before=fk(names,parents,list(first.values()))
            moved={k:v.copy() for k,v in pose.items()};moved['joints']+=np.array([.03,0,0])
            sender.submit(moved,PARENTS);second=bones()
            after=fk(names,parents,[second[n] for n in names])
            for side in ('Left','Right'):
                index=names.index(side+'LowerLeg')
                np.testing.assert_allclose(after[index],before[index],atol=1e-6)
            sender.configure_knees(False,False,0,'pear');sender.submit(moved,PARENTS)
            released=bones();free=fk(names,parents,[released[n] for n in names])
            self.assertGreater(np.linalg.norm(free[names.index('LeftLowerLeg')]-before[names.index('LeftLowerLeg')]),.025)
            self.assertFalse(sender.error)
        finally:
            sender.close();sender.thread.join(2);receiver.close()
        self.assertFalse(sender.thread.is_alive())

    def test_python_live_link_udp_knee_lock(self):
        sender=PythonLiveLink();peer=Peer()
        try:
            peer.send(sender,'LiveLinkConnectMessage',{})
            sender.configure_knees(True,True,0,'pear')
            pose,_,_=fixture();sender.submit_live(pose,PARENTS)
            _,static=peer.wait('LiveLinkSkeletonStaticData')
            names=static['BoneNames'];parents=static['BoneParents']
            def read():
                _,frame=peer.wait('LiveLinkAnimationFrameData')
                local=[]
                for bone in frame['Transforms']:
                    p=bone['Translation'];q=bone['Rotation']
                    local.append([p[a] for a in 'XYZ']+[q[a] for a in 'XYZW'])
                return fk(names,parents,local)
            first=read()
            moved={k:v.copy() for k,v in pose.items()};moved['joints']+=np.array([.03,0,0])
            sender.submit_live(moved,PARENTS)
            # Frames can already be in the socket. All valid held poses must
            # nevertheless retain the same two knee anchors.
            for _ in range(3):
                second=read()
                for hip,knee,ankle in leg_indices(names).values():
                    np.testing.assert_allclose(second[knee],first[knee],atol=1e-5)
            self.assertFalse(sender.error())
        finally:
            sender.close();sender.thread.join(2);peer.close()

if __name__=='__main__':unittest.main(verbosity=2)
