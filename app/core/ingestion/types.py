from dataclasses import dataclass, field

@dataclass
class Segment:
    doc_id: str
    index: int
    text: str
    location_label: str
    page: int | None = None
    # (start, end, bbox) entries; offsets are into text.
    spans: list[tuple[int, int, list[float]]] = field(default_factory=list)

@dataclass
class Chunk:
    id: str
    doc_id: str
    segment_index: int
    chunk_index: int
    text: str
    location_label: str
    page: int | None
    char_start: int
    char_end: int
    bboxes: list[list[float]] | None
    type: str = 'text'
