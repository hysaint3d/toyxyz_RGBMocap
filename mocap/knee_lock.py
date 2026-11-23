"""Manual knee contact anchors for outgoing poses, independent of model/axes.

Captures joint centres where the user enables each knee, without snapping to an
estimated floor. A bounded pelvis translation and rigid subtree rotations keep
both anchors and all current source bone lengths. Unreachable constraints raise
instead of stretching the legs. Source arrays are never modified.
"""
import numpy as np
from .pear_vmc import quaternion


def rotation(q):
    q=np.asarray(q,dtype=float)
    if q.shape!=(4,) or not np.isfinite(q).all() or abs(np.linalg.norm(q)-1)>.01:
        raise ValueError('Invalid knee-lock quaternion')
    x,y,z,w=q/np.linalg.norm(q)
    return np.array(((1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)),
                     (2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)),
                     (2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y))))


def unit(v):
    size=np.linalg.norm(v)
    if size<1e-9: raise ValueError('Degenerate knee-lock segment')
    return v/size


def aim(a,b):
    a,b=unit(a),unit(b); v=np.cross(a,b); c=float(np.clip(a@b,-1,1))
    if c<-.999999:
        axis=unit(np.cross(a,np.eye(3)[np.argmin(abs(a))]))
        return 2*np.outer(axis,axis)-np.eye(3)
    k=np.array(((0,-v[2],v[1]),(v[2],0,-v[0]),(-v[1],v[0],0)))
    return np.eye(3)+k+k@k/max(1+c,1e-12)


def pelvis_shift(centres,radii):
    """Nearest point to the original pelvis satisfying one/two thigh spheres."""
    c=centres[0]; radius=radii[0]
    if len(centres)==1: return c+radius*unit(-c)
    other=centres[1]; other_radius=radii[1]
    distance=np.linalg.norm(other-c)
    if distance<1e-8:
        if abs(radius-other_radius)>.0001:
            raise ValueError('Knee anchors conflict; release or re-anchor')
        return c+radius*unit(-c)
    if distance>radius+other_radius+1e-6 or distance<abs(radius-other_radius)-1e-6:
        raise ValueError('Knee anchors conflict; release or re-anchor')
    axis=(other-c)/distance
    along=(radius*radius-other_radius*other_radius+distance*distance)/(2*distance)
    centre=c+axis*along
    reach=np.sqrt(max(0.,radius*radius-along*along))
    direction=-centre+axis*np.dot(centre,axis)
    if np.linalg.norm(direction)<1e-8:
        direction=np.cross(axis,np.eye(3)[np.argmin(abs(axis))])
    return centre+reach*unit(direction)


def leg_indices(names):
    clean=[str(n).rsplit(':',1)[-1] for n in names]
    soma='LeftShin' in clean
    result={}
    for side in ('Left','Right'):
        alternatives=((side+'UpperLeg',side+'LowerLeg',side+'Foot'),
                      (side+'UpLeg',side+'Leg',side+'Foot'))
        if soma: alternatives=((side+'Leg',side+'Shin',side+'Foot'),)+alternatives
        for triple in alternatives:
            if all(n in clean for n in triple):
                result[side]=tuple(clean.index(n) for n in triple); break
    return result


class KneeLock:
    def __init__(self,metres_per_unit=1.):
        self.scale=metres_per_unit; self.reset()

    def reset(self):
        self.anchors={}; self.identity=None; self.side_revisions={}

    def apply(self,names,parents,positions,rotations,options):
        """options=(left, right, recapture revision, stable source identity)."""
        left,right,revision,identity=options
        if not (left or right):
            self.reset(); return positions,rotations
        global_revision=revision[0] if isinstance(revision,tuple) else revision
        if (identity,global_revision)!=self.identity:
            self.anchors={}; self.side_revisions={}; self.identity=(identity,global_revision)
        if isinstance(revision,tuple):
            for side,epoch in zip(('Left','Right'),revision[1:]):
                if self.side_revisions.get(side)!=epoch: self.anchors.pop(side,None)
                self.side_revisions[side]=epoch
        enabled={side for side,on in (('Left',left),('Right',right)) if on}
        for side in set(self.anchors)-enabled: del self.anchors[side]
        parents=np.asarray(parents,dtype=int)
        p=np.asarray(positions,dtype=float)*self.scale
        r=np.asarray(rotations,dtype=float)
        n=len(names)
        if (p.shape!=(n,3) or r.shape!=(n,3,3) or not np.isfinite(p).all()
                or not np.isfinite(r).all() or parents.shape!=(n,) or parents[0]!=-1
                or np.any(parents[1:]<0) or np.any(parents[1:]>=np.arange(1,n))):
            raise ValueError('Invalid knee-lock hierarchy or pose')
        if np.max(abs(r.swapaxes(-1,-2)@r-np.eye(3)))>.005 or np.min(np.linalg.det(r))<.99:
            raise ValueError('Knee lock requires rigid rotations')
        legs=leg_indices(names)
        if not enabled.issubset(legs): raise ValueError('Knee lock: unsupported leg names')
        j=p.copy(); world=r.copy()
        for i,parent in enumerate(parents):
            if parent>=0:
                j[i]=j[parent]+world[parent]@p[i]
                world[i]=world[parent]@r[i]
        original_j=j.copy(); original_r=world.copy()
        active=[legs[side] for side in ('Left','Right') if side in enabled]
        centres=[]; radii=[]
        for side in ('Left','Right'):
            if side not in enabled: continue
            hip,knee,ankle=legs[side]
            if parents[knee]!=hip or parents[ankle]!=knee:
                raise ValueError('Knee lock requires a direct hip-knee-ankle chain')
            if side not in self.anchors: self.anchors[side]=j[knee].copy()
            length=np.linalg.norm(j[knee]-j[hip])
            if length<1e-6 or np.linalg.norm(j[ankle]-j[knee])<1e-6:
                raise ValueError('Knee lock: zero leg length')
            centres.append(self.anchors[side]-j[hip]); radii.append(length)
        shift=pelvis_shift(centres,radii)
        if np.linalg.norm(shift)>.35:
            raise ValueError('Knee lock needs over 35 cm pelvis correction; release or re-anchor')
        j+=shift

        def turn(index,pivot,correction):
            affected=[index]
            for child in range(index+1,n):
                if int(parents[child]) in affected: affected.append(child)
            j[affected]=(j[affected]-pivot)@correction.T+pivot
            world[affected]=correction@world[affected]

        for side in ('Left','Right'):
            if side not in enabled: continue
            hip,knee,ankle=legs[side]; anchor=self.anchors[side]
            turn(hip,j[hip].copy(),aim(j[knee]-j[hip],anchor-j[hip]))
            # The ankle follows the closest reachable direction to its source
            # position. Knee contact has priority; this is not a foot lock.
            direction=original_j[ankle]-anchor
            if np.linalg.norm(direction)<1e-7: direction=j[ankle]-j[knee]
            turn(knee,j[knee].copy(),aim(j[ankle]-j[knee],direction))
            turn(ankle,j[ankle].copy(),original_r[ankle]@world[ankle].T)
            if np.linalg.norm(j[knee]-anchor)>1e-5:
                raise ValueError('Knee lock failed to reach its anchor')
        out_p=j.copy(); out_r=world.copy()
        for i,parent in enumerate(parents):
            if parent>=0:
                out_p[i]=world[parent].T@(j[i]-j[parent])
                out_r[i]=world[parent].T@world[i]
        return out_p/self.scale,out_r

    def bones(self,bones,parents,options):
        if not any(options[:2]): self.reset(); return bones
        names=[b[0] for b in bones]
        p,r=self.apply(names,parents,[b[1] for b in bones],
                       [rotation(b[2]) for b in bones],options)
        return [(name,point,quaternion(matrix)) for name,point,matrix in zip(names,p,r)]

    def poses(self,names,parents,poses,options):
        if not any(options[:2]): self.reset(); return poses
        array=np.asarray(poses,dtype=float)
        p,r=self.apply(names,parents,array[:,:3],[rotation(q) for q in array[:,3:]],options)
        return [list(point)+quaternion(matrix).tolist() for point,matrix in zip(p,r)]


def vmc_parents(names):
    lookup={name:i for i,name in enumerate(names)}
    parents={'Hips':None,'Spine':'Hips','Chest':'Spine','UpperChest':'Chest',
             'Neck':'UpperChest','Head':'Neck'}
    for side in ('Left','Right'):
        for chain,root in ((('UpperLeg','LowerLeg','Foot','Toes'),'Hips'),
                           (('Shoulder','UpperArm','LowerArm','Hand'),'UpperChest')):
            previous=root
            for bone in chain: parents[side+bone]=previous; previous=side+bone
        for finger in ('Thumb','Index','Middle','Ring','Little'):
            previous=side+'Hand'
            for segment in ('Proximal','Intermediate','Distal'):
                parents[side+finger+segment]=previous; previous=side+finger+segment
    return [-1 if parents[name] is None else lookup[parents[name]] for name in names]
