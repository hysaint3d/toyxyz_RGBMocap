"""Independent Stream target; keeps the official Unreal sender untouched."""
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import (QWidget,QFormLayout,QLineEdit,QSpinBox,QPushButton,
                               QLabel,QListWidgetItem,QCheckBox,QGroupBox)
from .python_livelink import TARGET, PROVIDER


class PythonLiveLinkWorkspace:
    def build_python_livelink(self,column):
        self.python_livelink_sender=None; self._python_livelink_closing=[]
        self._python_scope=None; self._python_error=None
        self.python_livelink_controls=QWidget(); form=QFormLayout(self.python_livelink_controls)
        form.setContentsMargins(0,0,0,0)
        self.python_livelink_ip=QLineEdit('127.0.0.1')
        self.python_livelink_port=QSpinBox(); self.python_livelink_port.setRange(0,65535)
        self.python_livelink_port.setValue(0); self.python_livelink_port.setSpecialValueText('Automatic')
        self.python_livelink_endpoint=QLineEdit(); self.python_livelink_endpoint.setPlaceholderText('Optional UE IPv4:port')
        self.python_livelink_button=QPushButton('Start Python Live Link'); self.python_livelink_button.setCheckable(True)
        self.python_livelink_button.toggled.connect(self.python_livelink_toggle)
        note=QLabel('Experimental body/finger stream. In UE enable Live Link and UDP Messaging, then add Message Bus Source > '+PROVIDER+'.\nSource rig / retarget setup is required. No automatic MetaHuman connection.'); note.setWordWrap(True)
        form.addRow('Local IPv4',self.python_livelink_ip)
        form.addRow('Local UDP port',self.python_livelink_port)
        form.addRow('UE static endpoint',self.python_livelink_endpoint)
        form.addRow(self.python_livelink_button); form.addRow(note)
        column.addWidget(self.python_livelink_controls); self.python_livelink_controls.hide()
        self._knee_revision=0; self._knee_epochs=[0,0]
        self._knee_context=None; self._knee_last_frames={}
        self.stream_knee_controls=QGroupBox('Kneeling contact lock (manual)')
        knee_form=QFormLayout(self.stream_knee_controls)
        self.stream_left_knee=QCheckBox('Lock left knee')
        self.stream_right_knee=QCheckBox('Lock right knee')
        self.stream_knee_reset=QPushButton('Re-anchor knees')
        for side,control in enumerate((self.stream_left_knee,self.stream_right_knee)):
            control.toggled.connect(lambda checked,side=side:self.stream_knee_toggled(side))
            knee_form.addRow(control)
        self.stream_knee_reset.clicked.connect(self.stream_knee_reanchor)
        knee_form.addRow(self.stream_knee_reset)
        note=QLabel('Kneel first, then enable a knee. Locks its current joint position for each streamed person. Output only; knees have priority over feet. Release before standing.'); note.setWordWrap(True)
        knee_form.addRow(note); column.addWidget(self.stream_knee_controls)
        self.stream_knee_controls.hide()

    def stream_knee_changed(self,*args):
        self._vmc_frame_key=None
        self.update_stream()

    def stream_knee_toggled(self,side):
        self._knee_epochs[side]+=1; self.stream_knee_changed()

    def stream_knee_reanchor(self,*args):
        self._knee_revision+=1; self.stream_knee_changed()

    def configure_stream_knees(self,sender,context,frames=()):
        # Never retain a contact anchor across a source/take or timeline jump.
        current=dict(frames)
        if context!=self._knee_context or any(ident in self._knee_last_frames and
                (frame<self._knee_last_frames[ident] or frame-self._knee_last_frames[ident]>10)
                for ident,frame in current.items()):
            self._knee_revision+=1
        self._knee_context=context; self._knee_last_frames=current
        sender.configure_knees(self.stream_left_knee.isChecked(),self.stream_right_knee.isChecked(),
            (self._knee_revision,*self._knee_epochs),repr(context))

    def configure_live_knees(self,sender,meta):
        pose=self.motion_view.live_data
        self.configure_stream_knees(sender,('pear',getattr(self,'pear_generation',None),
            pose.get('rig_revision') if pose else None, bool(meta and meta.get('aligned'))))

    def python_livelink_toggle(self,enabled):
        self._python_error=None
        if enabled:
            try:
                from .python_livelink import PythonLiveLink
                self.python_livelink_sender=PythonLiveLink(self.python_livelink_ip.text(),
                    self.python_livelink_port.value(),self.python_livelink_endpoint.text())
            except (OSError,ValueError) as exc:
                self._python_error=str(exc)
                with QSignalBlocker(self.python_livelink_button): self.python_livelink_button.setChecked(False)
        else:
            sender=self.python_livelink_sender; self.python_livelink_sender=None
            if sender is not None:
                sender.close(); self._python_livelink_closing.append(sender)
        running=self.python_livelink_sender is not None
        for widget in (self.python_livelink_ip,self.python_livelink_port,self.python_livelink_endpoint):
            widget.setEnabled(not running)
        self.python_livelink_button.setText('Stop Python Live Link' if running else 'Start Python Live Link')
        if hasattr(self,'_stream_timer') and self.stream_target.currentText()==TARGET:
            self.stream_tab_changed(self.people_tabs.currentIndex())

    def python_livelink_stop(self):
        if hasattr(self,'python_livelink_button'): self.python_livelink_button.setChecked(False)

    def pear_vmc_stop(self):
        self.python_livelink_stop()
        method=getattr(super(),'pear_vmc_stop',None)
        if method: method()

    def pear_vmc_publish(self,meta=None):
        if self.stream_target.currentText()==TARGET:
            sender=self.python_livelink_sender
            if sender is not None and self._pear_active:
                self.configure_live_knees(sender,meta)
                sender.submit_live(self.motion_view.live_data if meta and meta.get('type')=='frame' else None,
                    getattr(self.motion_view,'live_parents',None),bool(meta and meta.get('aligned')))
            return
        if self.stream_target.currentText()=='VMC' and self._pear_active and self.pear_vmc_sender is not None:
            self.configure_live_knees(self.pear_vmc_sender,meta)
        method=getattr(super(),'pear_vmc_publish',None)
        if method: method(meta)

    def update_python_livelink(self):
        self._python_livelink_closing=[s for s in self._python_livelink_closing if s.thread.is_alive()]
        self.python_livelink_button.setEnabled(not self._python_livelink_closing)
        live=self._pear_active
        scope=('pear-live',) if live else (self.people_root or self.project,self.model_choice.currentData())
        sender=self.python_livelink_sender
        if scope!=self._python_scope:
            self._python_scope=scope; self._stream_scope=scope
            self._stream_checked.clear(); self._stream_rows=None
            if sender is not None: sender.submit_live(None) if live else sender.publish(())
        self.stream_people.setVisible(not live)
        rows=() if live else self.stream_people_with_motion()
        if rows!=self._stream_rows:
            self._stream_checked.intersection_update(i for i,_ in rows)
            with QSignalBlocker(self.stream_people):
                self.stream_people.clear()
                for ident,name in rows:
                    item=QListWidgetItem(name,self.stream_people); item.setData(Qt.UserRole,ident)
                    item.setFlags(item.flags()|Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked if ident in self._stream_checked else Qt.Unchecked)
            self._stream_rows=rows
        if sender is not None and not live:
            try:
                sources=tuple(self.stream_sources_at_playhead(rows))
                self.configure_stream_knees(sender,(scope,tuple((ident,rig.key,id(frames),repr(transform))
                    for ident,name,rig,frames,frame,transform in sources)),
                    tuple((ident,frame) for ident,name,rig,frames,frame,transform in sources))
                actors=tuple((self.stream_actor_id(ident),name,rig,frame,frames[frame],transform)
                    for ident,name,rig,frames,frame,transform in sources)
                sender.publish(actors)
            except (OSError,ValueError,IndexError,KeyError,TypeError) as exc:
                sender.publish(()); self._python_error=str(exc)
            else: self._python_error=None
        if sender is None:
            status='Output off. '+('Start PEAR tracking separately.' if live else 'Check people, then Start Python Live Link.')
        elif sender.error(): status='Python Live Link: '+sender.error()
        elif not sender.ready and not sender.thread.is_alive(): status='Python Live Link stopped. Stop and start to retry.'
        elif not sender.connected: status=f'Waiting for UE Message Bus Source > {PROVIDER}. Local port {sender.port}.'
        else: status=f'Connected: {sender.subjects} subjects, {sender.frames} pose batches sent.'
        self.stream_status.setText(self._python_error or status)
