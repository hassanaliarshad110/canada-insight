"""The common data model: the shapes every city's data is turned into, whatever its portal or terminology.

Phase 1 uses Source, QualityCheck, Area, Facility, Home and Observation. The other entities in
docs/architecture.md (population observations, service requests, development activity, capital investments) follow
the same pattern and are added with the modules that need them.

Every value published carries a `kind`, so the interface can tell the four apart:
  official     reported by the publisher as-is (a count from an inventory, a Census figure)
  calculated   worked out by this platform from official data with a documented formula
  estimate     modelled (an assumption is involved: a forecast, an allocation, an imputed unit count)
  ai           written by an AI assistant (never stored as data; shown labelled in the interface)
"""
from dataclasses import dataclass, field, asdict
from typing import Optional

KINDS = ('official', 'calculated', 'estimate', 'ai')
LEVELS = ('city', 'ward', 'community', 'neighbourhood', 'census_tract', 'dissemination_area')


@dataclass
class Source:
    id: str                       # stable key within the city, e.g. 'calgary.parcels'
    title: str                    # the publisher's own dataset title
    publisher: str
    url: str                      # human page for the dataset
    api: str                      # endpoint actually read
    licence: str
    coverage: str                 # geographic coverage
    period: str                   # reporting period the data describes
    unit: str                     # what one row is
    limitations: list = field(default_factory=list)
    publisher_updated: Optional[str] = None   # publisher's last update (ISO date), read at fetch time
    fetched_at: Optional[str] = None          # when this build read it (ISO, UTC)
    rows: Optional[int] = None
    query: Optional[str] = None               # filter used, verbatim
    sha256: Optional[str] = None              # hash of the rows as read, for reproducibility
    transformations: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


@dataclass
class QualityCheck:
    source: str
    check: str                    # e.g. 'missing_geometry'
    status: str                   # 'pass', 'warn' or 'fail'
    detail: str
    value: Optional[float] = None
    threshold: Optional[float] = None

    def to_dict(self):
        return asdict(self)


@dataclass
class Area:
    code: str
    name: str
    level: str                    # one of LEVELS
    city: str
    parent: Optional[str] = None  # e.g. the ward holding most of a community
    attrs: dict = field(default_factory=dict)


@dataclass
class Facility:
    id: str
    kind: str                     # the city config's amenity key, e.g. 'playground'
    x: float                      # projected metres (points); polygons keep their rings in `shape`
    y: float
    shape: Optional[list] = None
    capacity: Optional[float] = None
    attrs: dict = field(default_factory=dict)


@dataclass
class Home:
    id: str                       # the publisher's record id (assessment roll number)
    area: Optional[str]           # community code as published by the city
    x: float
    y: float
    built: Optional[int]          # year of construction
    weight: float = 1.0           # dwelling units this record stands for
    weight_kind: str = 'official' # 'official' (1 per record) or 'estimate' (units estimated)


@dataclass
class Observation:
    metric: str
    area: str
    level: str
    value: Optional[float]
    kind: str                     # one of KINDS
    period: str
    sources: list
    note: Optional[str] = None
