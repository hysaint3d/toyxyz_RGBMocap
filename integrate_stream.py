"""Narrow Stream integration for the VMC fork and upstream Stream layouts."""
import ast

MARKER='from .python_livelink_ui import PythonLiveLinkWorkspace'

def integrate(text):
    if MARKER in text:
        return text
    ast.parse(text)
    if 'class StreamWorkspace(VmcStreamWorkspace):' in text:
        text=text.replace('class StreamWorkspace(VmcStreamWorkspace):',MARKER+'\n\nclass StreamWorkspace(PythonLiveLinkWorkspace, VmcStreamWorkspace):',1)
    elif 'class StreamWorkspace:' in text:
        text=text.replace('class StreamWorkspace:',MARKER+'\n\nclass StreamWorkspace(PythonLiveLinkWorkspace):',1)
    else:
        raise ValueError('Unsupported StreamWorkspace layout; no files changed')
    anchor="        self.stream_target.setAccessibleName('Stream target')"
    if text.count(anchor)!=1: raise ValueError('Unsupported Stream target controls')
    text=text.replace(anchor,"        self.stream_target.addItem('Python Live Link (SaintMocap)')\n"+anchor,1)
    anchor='        self.stream_people = QListWidget()'
    if text.count(anchor)!=1: raise ValueError('Unsupported Stream people controls')
    text=text.replace(anchor,'        self.build_python_livelink(column)\n'+anchor,1)
    hooks={
        'stream_tab_changed(self, index)':'''        if self.stream_target.currentText() == 'Python Live Link (SaintMocap)':
            self.update_stream()
            self._stream_timer.start(33 if self.python_livelink_sender is not None else 250)
            return
''',
        'change_stream_target(self, index)':'''        self.python_livelink_stop()
        self.python_livelink_controls.setVisible(self.stream_target.currentText() == 'Python Live Link (SaintMocap)')
        self.stream_people.show()
''',
        'close_stream(self)':'''        self.python_livelink_stop()
''',
        'update_stream(self)':'''        if self.stream_target.currentText() == 'Python Live Link (SaintMocap)':
            self.update_python_livelink()
            return
''',
    }
    for method,code in hooks.items():
        anchor='    def '+method+':\n'
        if text.count(anchor)!=1: raise ValueError('Unsupported Stream method: '+method)
        text=text.replace(anchor,anchor+code,1)
    ast.parse(text)
    return text
