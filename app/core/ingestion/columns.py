"""Reading order for text blocks. Each block is (x0,y0,x1,y1,text,...)."""

def order_blocks(blocks, width):
    def category(block):
        x0, _, x1, *_ = block
        if x1 - x0 > .6 * width: return 'full'
        if x1 <= .55 * width: return 'left'
        if x0 >= .45 * width: return 'right'
        return 'full'
    blocks = sorted(blocks, key=lambda b: (b[1],b[0]))
    if not any(category(b) == 'right' for b in blocks): return blocks
    output, group = [], []
    def flush():
        output.extend(sorted((b for b in group if category(b) == 'left'), key=lambda b:(b[1],b[0])))
        output.extend(sorted((b for b in group if category(b) == 'right'), key=lambda b:(b[1],b[0])))
        group.clear()
    for b in blocks:
        if category(b) == 'full':
            flush(); output.append(b)
        else: group.append(b)
    flush()
    return output
