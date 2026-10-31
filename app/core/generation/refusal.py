import re
MARKER='[[NOT_FOUND]]'
PREFIX='I could not find this in the selected documents.'

class RefusalBuffer:
    """Never emit the initial buffer until a split refusal marker is recognizable."""
    def __init__(self): self.buffer='';self.decided=False;self.refused=False
    def feed(self,text,final=False):
        if self.decided: return text
        self.buffer+=text
        if len(self.buffer)<20 and not final: return ''
        self.decided=True
        data=self.buffer;self.buffer=''
        if data.startswith(MARKER):
            self.refused=True
            rest=data[len(MARKER):].lstrip()
            return PREFIX+(' '+rest if rest else '')
        return data

def cited_markers(content, count):
    markers={int(m) for m in re.findall(r'(?<!\[)\[(\d+)\](?!\])',content)}
    return {n for n in markers if 1<=n<=count}, sorted(n for n in markers if n<1 or n>count)
