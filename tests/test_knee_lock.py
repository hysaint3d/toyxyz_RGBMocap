"""Contact invariants and sender integration, without models or avatar assets."""
import sys
from pathlib import Path
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).parents[1]))
from mocap.knee_lock import KneeLock,rotation
from mocap.pear_vmc import quaternion


def fixture(soma=False):
    names=['Hips','LeftUpLeg','LeftLeg','LeftFoot','LeftToeBase',
           'RightUpLeg','RightLeg','RightFoot','RightToeBase','Spine','Head']
    if soma:
        names[1:3]=['LeftLeg','LeftShin']; names[5:7]=['RightLeg','RightShin']
    parents=np.array([-1,0,1,2,3,0,5,6,7,0,9])
    p=np.array([[0,.6,0],[.12,0,0],[0,-.5,0],[0,0,-.4],[0,0,.1],
                [-.12,0,0],[0,-.5,0],[0,0,-.4],[0,0,.1],[0,.15,0],[0,.3,0]])
    r=np.tile(np.eye(3),(len(names),1,1))
    return names,parents,p,r


def fk(parents,p,r):
    j=np.array(p,copy=True); world=np.array(r,copy=True)
    for i,parent in enumerate(parents):
        if parent>=0:
            j[i]=j[parent]+world[parent]@p[i];world[i]=world[parent]@r[i]
    return j,world


class KneeLockTests(unittest.TestCase):
    def test_single_and_double_contact_lengths_and_foot_orientation(self):
        for sides in ((True,False),(False,True),(True,True)):
            for soma in (False,True):
                names,parents,p,r=fixture(soma); solver=KneeLock()
                options=(*sides,0,'actor/take')
                first=solver.apply(names,parents,p,r,options)
                np.testing.assert_allclose(first[0],p,atol=1e-12)
                anchors=fk(parents,p,r)[0]
                moved=p.copy();moved[0]+=[.06,.01,.04]
                # Root yaw changes the hip positions while both knees remain planted.
                angle=.12; rot=r.copy();rot[0]=[[np.cos(angle),0,np.sin(angle)],[0,1,0],[-np.sin(angle),0,np.cos(angle)]]
                before=moved.copy();before_r=rot.copy()
                corrected,corrected_r=solver.apply(names,parents,moved,rot,options)
                joints,world=fk(parents,corrected,corrected_r)
                _,source_r=fk(parents,moved,rot)
                for enabled,knee,foot in zip(sides,(2,6),(3,7)):
                    if enabled:
                        np.testing.assert_allclose(joints[knee],anchors[knee],atol=1e-8)
                        np.testing.assert_allclose(world[foot],source_r[foot],atol=1e-8)
                np.testing.assert_allclose(np.linalg.norm(corrected[1:],axis=1),np.linalg.norm(moved[1:],axis=1),atol=1e-8)
                np.testing.assert_allclose(np.linalg.det(corrected_r),1,atol=1e-8)
                np.testing.assert_array_equal(moved,before);np.testing.assert_array_equal(rot,before_r)

    def test_disable_recapture_identity_and_loss_reset(self):
        names,parents,p,r=fixture(); solver=KneeLock()
        solver.apply(names,parents,p,r,(True,False,0,'one'))
        p=p.copy();p[0,0]+=.07
        for options in ((True,False,1,'one'),(True,False,1,'other')):
            a,b=solver.apply(names,parents,p,r,options)
            np.testing.assert_allclose(a,p,atol=1e-12)
        solver.reset(); a,b=solver.apply(names,parents,p,r,(True,False,1,'other'))
        np.testing.assert_allclose(a,p,atol=1e-12)
        a,b=solver.apply(names,parents,p,r,(False,False,1,'other'))
        self.assertIs(a,p);self.assertIs(b,r);self.assertFalse(solver.anchors)

    def test_centimetre_and_metre_output_agree(self):
        names,parents,p,r=fixture(); poses=np.concatenate((p,np.tile([0,0,0,1],(len(p),1))),axis=1)
        metre=KneeLock();cm=KneeLock(.01)
        a=poses.copy();b=poses.copy();b[:,:3]*=100
        metre.poses(names,parents,a,(True,True,0,'a'));cm.poses(names,parents,b,(True,True,0,'a'))
        a[0,0]+=.04;b[0,0]+=4
        left=np.array(metre.poses(names,parents,a,(True,True,0,'a')))
        right=np.array(cm.poses(names,parents,b,(True,True,0,'a')));right[:,:3]*=.01
        np.testing.assert_allclose(left,right,atol=1e-9)

    def test_independent_reenable_epoch_keeps_other_anchor(self):
        names,parents,p,r=fixture();solver=KneeLock()
        solver.apply(names,parents,p,r,(True,True,(0,1,1),'a'))
        left=solver.anchors['Left'].copy(); right=solver.anchors['Right'].copy()
        moved=p.copy();moved[0,0]+=.025
        # Right was toggled off/on between processed frames; only it recaptures.
        solver.apply(names,parents,moved,r,(True,True,(0,1,3),'a'))
        np.testing.assert_array_equal(solver.anchors['Left'],left)
        self.assertGreater(np.linalg.norm(solver.anchors['Right']-right),.02)

    def test_conflicting_or_excessive_correction_and_invalid_pose(self):
        names,parents,p,r=fixture();solver=KneeLock()
        solver.apply(names,parents,p,r,(True,True,0,'a'))
        solver.anchors['Left']+=np.array([4,0,0])
        with self.assertRaisesRegex(ValueError,'conflict'):solver.apply(names,parents,p,r,(True,True,0,'a'))
        solver=KneeLock();solver.apply(names,parents,p,r,(True,False,0,'a'))
        moved=p.copy();moved[0,0]+=2
        with self.assertRaisesRegex(ValueError,'35 cm'):solver.apply(names,parents,moved,r,(True,False,0,'a'))
        broken=r.copy();broken[1,0,0]=np.nan
        with self.assertRaises(ValueError):solver.apply(names,parents,p,broken,(True,False,0,'a'))

if __name__=='__main__':unittest.main(verbosity=2)
