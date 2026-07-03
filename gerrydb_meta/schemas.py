"""User-facing schemas for GerryDB objects."""

from datetime import datetime
from typing import Annotated, Any, Mapping, Optional, Union
from uuid import UUID

from pydantic import (
    AliasPath,
    AnyUrl,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from gerrydb_meta import enums, models

UserEmail = Annotated[
    str,
    Field(max_length=255, min_length=3, pattern=r"^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$"),
]
# / allowed at start. 1-2 segments. Used for objects that are not namespaced like
# localities.
GerryPath = Annotated[
    str,
    Field(
        pattern=r"^/?[a-z0-9][a-z0-9-_.:]+(?:/[a-z0-9][a-z0-9-_.:]+){0,1}$",
        max_length=255,
        min_length=2,
    ),
]
# / allowed at start. 1-3 segments. Leading character from each segment must be a-z0-9. No
# uppercase characters allowed. Used for namespaced objects like columns, column sets, etc.
NamespacedGerryPath = Annotated[
    str,
    Field(
        pattern=r"^/?[a-z0-9][a-z0-9-_.:]+(?:/[a-z0-9][a-z0-9-_.:]+){0,2}$",
        max_length=255,
        min_length=2,
    ),
]
# / allowed at start. 1-3 segments. Leading character from each segment must be a-z0-9 and A-Z
# allowed in last segment for weird GEOIDs.
NamespacedGerryGeoPath = Annotated[
    str,
    Field(
        pattern=r"^/?[a-z0-9][a-z0-9-_.:]+(?:/[a-z0-9][a-z0-9-_.:]+){0,1}"
        r"(?:/[a-zA-Z0-9][a-zA-Z0-9-_.:]+){0,1}$",
        max_length=255,
        min_length=2,
    ),
]
# No capital letters allowed
NameStr = Annotated[
    str,
    Field(
        pattern=r"^[a-z0-9][a-z0-9-_.:]+$",
        max_length=100,
        min_length=2,
    ),
]
# Capital letters allowed because some vtds suck
GeoNameStr = Annotated[
    str,
    Field(pattern=r"^[a-z0-9][a-zA-Z0-9-_.:]+$", max_length=100, min_length=2),
]
Description = Optional[
    Annotated[
        str,
        Field(max_length=5000, min_length=1),
    ]
]
ShortStr = Optional[
    Annotated[
        str,
        Field(max_length=100, min_length=1),
    ]
]


class ObjectMetaBase(BaseModel):
    """Base model for object metadata."""

    notes: Description = None


class ObjectMetaCreate(ObjectMetaBase):
    """Object metadata received on creation."""


class ObjectMeta(ObjectMetaBase):
    """Object metadata returned by the database."""

    uuid: UUID
    created_at: datetime
    created_by: UserEmail

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_attributes(cls, obj: models.ObjectMeta):
        return cls(
            uuid=str(obj.uuid),
            notes=obj.notes,
            created_at=obj.created_at,
            created_by=obj.user.email,
        )


class LocalityBase(BaseModel):
    """Base model for locality metadata."""

    canonical_path: GerryPath
    parent_path: Optional[GerryPath] = None
    default_proj: ShortStr = None
    name: ShortStr = None


class LocalityCreate(LocalityBase):
    """Locality metadata received on creation."""

    aliases: Optional[list[NameStr]] = None


class LocalityPatch(BaseModel):
    """Locality metadata received on PATCH."""

    aliases: list[NameStr] = None


class Locality(LocalityBase):
    """A locality returned by the database."""

    aliases: list[NameStr]
    meta: ObjectMeta

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_attributes(cls, obj: models.Locality):
        canonical_path = obj.canonical_ref.path
        return cls(
            canonical_path=canonical_path,
            parent_path=obj.parent.canonical_ref.path if obj.parent else None,
            name=obj.name,
            meta=ObjectMeta.from_attributes(obj.meta),
            aliases=[ref.path for ref in obj.refs if ref.path != canonical_path],
            default_proj=obj.default_proj,
        )


class NamespaceBase(BaseModel):
    """Base model for namespace metadata."""

    path: NameStr
    description: Description = None
    public: bool


class NamespaceCreate(NamespaceBase):
    """Namespace metadata received on creation."""


class Namespace(NamespaceBase):
    """A namespace returned by the database."""

    meta: ObjectMeta

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_attributes(cls, obj: models.Namespace):
        return cls(
            path=obj.path,
            description=obj.description,
            public=obj.public,
            meta=ObjectMeta.from_attributes(obj.meta),
        )


class ColumnBase(BaseModel):
    """Base model for locality metadata."""

    canonical_path: NamespacedGerryPath
    description: Description = None
    source_url: Optional[AnyUrl] = None
    kind: enums.ColumnKind
    type: enums.ColumnType


class ColumnCreate(ColumnBase):
    """Column metadata received on creation."""

    aliases: Optional[list[NameStr]] = None


class ColumnPatch(BaseModel):
    """Column metadata received on PATCH."""

    aliases: list[NameStr]


class Column(ColumnBase):
    """A locality returned by the database."""

    canonical_path: NamespacedGerryPath = Field(alias=AliasPath("canonical_ref", "path"))
    namespace: NameStr = Field(alias=AliasPath("namespace", "path"))
    aliases: list[NameStr] = Field(alias=AliasPath("canonical_ref", "aliases"))
    meta: ObjectMeta

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @classmethod
    def from_attributes(cls, obj: models.DataColumn | models.ColumnRef):
        root_obj = obj.column if isinstance(obj, models.ColumnRef) else obj
        canonical_path = root_obj.canonical_ref.path
        return cls(
            canonical_path=canonical_path,
            namespace=root_obj.namespace.path,
            description=root_obj.description,
            meta=ObjectMeta.from_attributes(root_obj.meta),
            aliases=[ref.path for ref in root_obj.refs if ref.path != canonical_path],
            kind=root_obj.kind,
            type=root_obj.type,
            source_url=(str(root_obj.source_url) if root_obj.source_url is not None else None),
        )


class ColumnValue(BaseModel):
    """Value of a column for a geography."""

    path: NamespacedGerryGeoPath
    value: Any


class GeoLayerBase(BaseModel):
    """Base model for geographic layer metadata."""

    path: NamespacedGerryPath
    description: Description = None
    source_url: Optional[AnyUrl] = None


class GeoLayerCreate(GeoLayerBase):
    """Geographic layer metadata received on creation."""


class GeoLayer(GeoLayerBase):
    """Geographic layer metadata returned by the database."""

    meta: ObjectMeta
    namespace: NameStr

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_attributes(cls, obj: models.GeoLayer):
        return cls(
            path=obj.path,
            namespace=obj.namespace.path,
            description=obj.description,
            source_url=str(obj.source_url) if obj.source_url is not None else None,
            meta=ObjectMeta.from_attributes(obj.meta),
        )


class GeoImport(BaseModel):
    """Geographic unit import metadata returned by the database."""

    uuid: UUID
    namespace: NameStr
    created_at: datetime
    created_by: UserEmail
    meta: ObjectMeta

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_attributes(cls, obj: models.GeoImport):
        return cls(
            uuid=str(obj.uuid),
            namespace=obj.namespace.path,
            created_at=obj.created_at,
            created_by=obj.user.email,
            meta=ObjectMeta.from_attributes(obj.meta),
        )


class GeographyBase(BaseModel):
    """Base model for a geographic unit."""

    path: GeoNameStr
    geography: Optional[bytes] = None
    internal_point: Optional[bytes] = None

    @field_validator("geography", "internal_point", mode="before")
    @classmethod
    def check_bytes_type(cls, v, info):
        if v is not None and not isinstance(v, bytes):
            field_name = info.field_name
            raise ValueError(f"The {field_name} must be of type bytes, got type {type(v).__name__}")
        return v


class GeographyCreate(GeographyBase):
    """Geographic unit data received on creation (geography as raw WKB bytes)."""


class GeographyPatch(GeographyBase):
    """Geographic unit data received on PATCH."""


class GeographyUpsert(GeographyBase):
    """Geographic unit data received on UPSERT (PUT)."""


class Geography(GeographyBase):
    """Geographic unit data returned by the database."""

    meta: ObjectMeta
    namespace: NameStr
    valid_from: datetime

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_attributes(cls, obj: models.GeoVersion):  # pragma: no cover
        return cls(
            namespace=obj.parent.namespace.path,
            geography=None if obj.geography is None else bytes(obj.geography.data),
            internal_point=(None if obj.internal_point is None else bytes(obj.internal_point.data)),
            path=obj.parent.path,
            meta=ObjectMeta.from_attributes(obj.parent.meta),
            valid_from=obj.valid_from,
        )


class GeographyMeta(BaseModel):
    """Geographic unit metadata returned by the database."""

    namespace: NameStr
    path: GeoNameStr
    meta: ObjectMeta

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_attributes(cls, obj: models.Geography):
        return cls(
            namespace=obj.namespace.path,
            path=obj.path,
            meta=ObjectMeta.from_attributes(obj.meta),
        )


class GeoSetCreate(BaseModel):
    """Paths to geographies in a `GeoSet`."""

    paths: list[GeoNameStr | NamespacedGerryGeoPath]


class ColumnSetBase(BaseModel):
    """Base model for a logical column grouping."""

    path: NameStr
    description: Description = None


class ColumnSetCreate(ColumnSetBase):
    """Column grouping data received on creation.
    The columns must first exist in the before a column set
    can be created with them.
    """

    columns: list[NamespacedGerryPath]


class ColumnSet(ColumnSetBase):
    """Logical column grouping returned by the database."""

    meta: ObjectMeta
    namespace: NameStr
    columns: list[Column]
    refs: list[NameStr]

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_attributes(cls, obj: models.ColumnSet):
        ordered_cols = sorted(obj.columns, key=lambda v: v.order)
        return cls(
            path=obj.path,
            description=obj.description,
            namespace=obj.namespace.path,
            columns=[Column.from_attributes(col.ref.column) for col in ordered_cols],
            refs=[col.ref.path for col in ordered_cols],
            meta=ObjectMeta.from_attributes(obj.meta),
        )


class ViewTemplateBase(BaseModel):
    """Base model for a view template."""

    path: NameStr
    description: Description = None


class ViewTemplateCreate(ViewTemplateBase):
    """View template data received on creation."""

    members: list[NamespacedGerryPath]


class ViewTemplatePatch(ViewTemplateBase):
    """View template data received on update."""

    members: list[NamespacedGerryPath]


class ViewTemplate(ViewTemplateBase):
    """View template returned by the database."""

    namespace: NameStr
    members: list[Column | ColumnSet]
    valid_from: datetime
    meta: ObjectMeta

    @classmethod
    def from_attributes(cls, obj: models.ViewTemplateVersion):
        members = sorted(obj.columns + obj.column_sets, key=lambda obj: obj.order)

        new_members = []

        for member in members:
            if isinstance(member.member, models.ColumnRef):
                new_members.append(Column.from_attributes(member.member.column))
            else:
                new_members.append(ColumnSet.from_attributes(member.member))

        return cls(
            path=obj.parent.path,
            namespace=obj.parent.namespace.path,
            description=obj.parent.description,
            members=new_members,
            valid_from=obj.valid_from,
            meta=ObjectMeta.from_attributes(obj.meta),
        )


class GraphBase(BaseModel):
    """Base model for a dual graph."""

    path: NameStr
    description: Description = None
    proj: ShortStr = None


WeightedEdge = tuple[
    Union[NamespacedGerryGeoPath, GeoNameStr],
    Union[NamespacedGerryGeoPath, GeoNameStr],
    Optional[dict],
]


class GraphCreate(GraphBase):
    """Dual graph definition received on creation."""

    locality: GerryPath
    layer: NamespacedGerryPath
    edges: list[WeightedEdge]


class GraphMeta(GraphBase):
    """Dual graph metadata returned by the database."""

    namespace: NameStr
    locality: Locality
    layer: GeoLayer
    meta: ObjectMeta
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_attributes(cls, obj: models.Graph):
        return cls(
            path=obj.path,
            namespace=obj.namespace.path,
            description=obj.description,
            locality=Locality.from_attributes(obj.set_version.loc),
            layer=GeoLayer.from_attributes(obj.set_version.layer),
            meta=ObjectMeta.from_attributes(obj.meta),
            created_at=obj.created_at,
        )


class Graph(GraphMeta):
    """Rendered dual graph without node attributes."""

    edges: list[WeightedEdge]

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_attributes(cls, obj: models.Graph):
        return cls(
            path=obj.path,
            namespace=obj.namespace.path,
            description=obj.description,
            locality=Locality.from_attributes(obj.set_version.loc),
            layer=GeoLayer.from_attributes(obj.set_version.layer),
            meta=ObjectMeta.from_attributes(obj.meta),
            created_at=obj.created_at,
            edges=[
                (edge.geo_1.full_path, edge.geo_2.full_path, edge.weights) for edge in obj.edges
            ],
        )


class PlanBase(BaseModel):
    """Base model for a districting plan."""

    path: NameStr
    description: Description = None
    source_url: Optional[AnyUrl] = None
    districtr_id: ShortStr = None
    daves_id: ShortStr = None


class PlanCreate(PlanBase):
    """Districting plan definition received on creation."""

    locality: GerryPath
    layer: NamespacedGerryPath
    assignments: dict[NamespacedGerryGeoPath, str]

    @field_validator("assignments", mode="before")
    @classmethod
    def _coerce_ints_to_str(cls, v: Any) -> Any:
        """
        If we receive {"23001": 1, "23003": 0, …}, turn each integer into a string.
        Otherwise, leave it as-is (Pydantic will still enforce that it ends up as str).
        """
        if isinstance(v, Mapping):
            return {k: str(val) for k, val in v.items()}
        return v


class PlanMeta(PlanBase):
    """Rendered districting plan (metadata only)."""

    namespace: NameStr
    locality: Locality
    layer: GeoLayer
    meta: ObjectMeta
    created_at: datetime
    num_districts: int
    complete: bool

    @classmethod
    def from_attributes(cls, obj: models.Plan):  # pragma: no cover
        return cls(
            path=obj.path,
            namespace=obj.namespace.path,
            description=obj.description,
            source_url=str(obj.source_url) if obj.source_url is not None else None,
            districtr_id=obj.districtr_id,
            daves_id=obj.daves_id,
            locality=obj.set_version.loc,
            layer=obj.set_version.layer,
            meta=ObjectMeta.from_attributes(obj.meta),
            created_at=obj.created_at,
            num_districts=obj.num_districts,
            complete=obj.complete,
        )


class Plan(PlanMeta):
    """Rendered districting plan."""

    assignments: dict[NamespacedGerryGeoPath, Optional[str]]

    @classmethod
    def from_attributes(cls, obj: models.Plan):
        # TODO: there's probably a performance bottleneck around the resolution
        # of geography names for assignments with a lot of geographies.
        base_geos = {member.geo.full_path: None for member in obj.set_version.members}
        assignments = {
            assignment.geo.full_path: assignment.assignment for assignment in obj.assignments
        }
        return cls(
            path=obj.path,
            namespace=obj.namespace.path,
            description=obj.description,
            source_url=str(obj.source_url) if obj.source_url is not None else None,
            districtr_id=obj.districtr_id,
            daves_id=obj.daves_id,
            locality=Locality.from_attributes(obj.set_version.loc),
            layer=GeoLayer.from_attributes(obj.set_version.layer),
            meta=ObjectMeta.from_attributes(obj.meta),
            created_at=obj.created_at,
            num_districts=obj.num_districts,
            complete=obj.complete,
            assignments={**base_geos, **assignments},
        )


class ViewBase(BaseModel):
    """Base model for a view."""

    path: NameStr


class ViewCreate(ViewBase):
    """View definition received on creation."""

    template: NamespacedGerryPath
    locality: NamespacedGerryPath
    layer: NamespacedGerryPath
    graph: Optional[NamespacedGerryPath] = None

    valid_at: Optional[datetime] = None
    proj: ShortStr = None


class ViewMeta(ViewBase):
    """View metadata returned by the database."""

    namespace: NameStr
    template: ViewTemplate
    locality: Locality
    layer: GeoLayer
    meta: ObjectMeta
    valid_at: datetime
    proj: ShortStr = None
    graph: Optional[GraphMeta]
    # TODO: add plans and geography paths?

    @classmethod
    def from_attributes(cls, obj: models.View):
        return cls(
            path=obj.path,
            namespace=obj.namespace.path,
            template=ViewTemplate.from_attributes(obj.template_version),
            locality=Locality.from_attributes(obj.loc),
            layer=GeoLayer.from_attributes(obj.layer),
            meta=ObjectMeta.from_attributes(obj.meta),
            valid_at=obj.at,
            proj=obj.proj,
            graph=None if obj.graph is None else GraphMeta.from_attributes(obj.graph),
        )
