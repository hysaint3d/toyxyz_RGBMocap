"""Real Qt widget lifecycle test, using fake transports and no model packages.

Run separately from the numerical suite. Optional argv[1] adds a Qt DLL folder
for host-provided Qt installations. Transport math/wire tests run independently.
"""
from pathlib import Path
import os
import sys
import types
import faulthandler
faulthandler.dump_traceback_later(15,exit=True)
os.environ['QT_QPA_PLATFORM']='offscreen'
_dll_handle=os.add_dll_directory(sys.argv[1]) if len(sys.argv)>1 and hasattr(os,'add_dll_directory') else None
ROOT=Path(__file__).parents[1]; sys.path.insert(0,str(ROOT))
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QWidget,QTabWidget,QVBoxLayout,QComboBox

class FakeSender:
    def __init__(self,*args):
        self.ready=True; self.connected=True; self.frames=0; self.subjects=0
        self.port=12345; self.stopped=False; self.poses=[]
        self.thread=types.SimpleNamespace(is_alive=lambda:False)
    def publish(self,poses): self.poses.append(poses)
    def submit_live(self,*args): self.poses.append(args)
    def close(self): self.stopped=True
    def error(self): return None

transport=types.ModuleType('mocap.python_livelink')
transport.TARGET='Python Live Link (SaintMocap)'; transport.PROVIDER='RGB MoCap Python (SaintMocap)'
transport.PythonLiveLink=FakeSender
sys.modules['mocap.python_livelink']=transport
bone=types.ModuleType('mocap.bone_stream')
bone.BoneStream=FakeSender; bone.PORT=49168; bone.MAX_ACTORS=128; bone.MAX_BAKE_FRAMES=36000
sys.modules['mocap.bone_stream']=bone
from mocap.stream_ui import StreamWorkspace

class Harness(StreamWorkspace,QWidget):
    def __init__(self):
        super().__init__(); self._pear_active=False; self.people_state=None
        self.people_root=None; self.project=Path('first'); self._single_actor={'name':'Actor'}
        self.model_choice=QComboBox(); self.model_choice.addItem('ExMR','exmr')
        self.motion_view=types.SimpleNamespace(target_frames=None,target_asset=None,index=0,
                                              live_data={'sample':1},live_parents=[-1])
        self.log=[]; self.people_tabs=QTabWidget(); layout=QVBoxLayout(self)
        layout.addWidget(self.people_tabs); self.people_tabs.addTab(QWidget(),'People')
        self.people_tabs.addTab(self.build_stream_page(),'Stream')
        self.people_tabs.currentChanged.connect(self.stream_tab_changed)
    def stream_people_with_motion(self): return ((1,'Actor'),(2,'Actor 2'))
    def stream_sources_at_playhead(self,rows):
        return iter((i,name,types.SimpleNamespace(key='rig'),['frame0','frame1'],self.motion_view.index,None)
                    for i,name in rows if i in self._stream_checked)

app=QApplication([]); ui=Harness()
ui.stream_target.setCurrentText(transport.TARGET); ui.people_tabs.setCurrentIndex(1)
assert ui.stream_target.count()==4
assert not ui.python_livelink_controls.isHidden()
assert ui.stream_vmc_controls.isHidden() and ui.stream_port_controls.isHidden()
ui.stream_people.item(0).setCheckState(Qt.Checked); ui.python_livelink_button.click()
sender=ui.python_livelink_sender
assert sender is not None and not ui.python_livelink_ip.isEnabled()
assert sender.poses[-1][0][4]=='frame0'
ui.motion_view.index=1; ui.update_stream(); assert sender.poses[-1][0][4]=='frame1'
ui.stream_people.item(1).setCheckState(Qt.Checked); assert len(sender.poses[-1])==2
before=sender.poses[-1][0][0]
ui.project=Path('second'); ui.update_stream(); assert not ui._stream_checked
ui.stream_people.item(0).setCheckState(Qt.Checked); assert sender.poses[-1][0][0]!=before
ui._pear_active=True; ui.update_stream(); assert ui.stream_people.isHidden()
ui.pear_vmc_publish({'type':'frame','aligned':True}); assert sender.poses[-1][0]=={'sample':1}
ui.pear_vmc_publish(); assert sender.poses[-1][0] is None
ui.pear_vmc_stop(); assert ui.python_livelink_sender is None and sender.stopped
ui._pear_active=False; ui.stream_target.setCurrentText('VMC')
assert ui.python_livelink_controls.isHidden() and not ui.stream_vmc_controls.isHidden()
ui.stream_target.setCurrentText(transport.TARGET); ui.python_livelink_button.click()
sender=ui.python_livelink_sender; ui.close_stream()
assert sender.stopped and ui.python_livelink_sender is None
ui.stream_target.setCurrentText('None'); ui._stream_timer.stop(); ui.close()
print('PASS: real Qt controls, source selection, playhead, project identity, PEAR routing, mode switching, stop/close; fake transports only.')
