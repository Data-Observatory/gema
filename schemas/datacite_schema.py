"""DataCite metadata schema matching metadata_template.json."""

from pydantic import BaseModel
from typing import Optional


class NameIdentifier(BaseModel):
    name_identifier: str = ""
    name_identifier_scheme: str = ""
    scheme_uri: str = ""


class Affiliation(BaseModel):
    affiliation: str = ""
    affiliation_identifier: str = ""
    affiliation_identifier_scheme: str = ""


class Creator(BaseModel):
    creator_name: str = ""
    creator_name_type: str = ""
    given_name: str = ""
    family_name: str = ""
    email: str = ""
    genre: str = ""
    type: str = ""
    contributor_type: str = ""
    name_identifiers: list[NameIdentifier] = []
    affiliations: list[Affiliation] = []


class Publisher(BaseModel):
    publisher_name: str = ""
    publisher_identifier: str = ""
    publisher_identifier_scheme: str = ""
    publisher_scheme_uri: str = ""


class Title(BaseModel):
    name: str = ""
    title_type: str = ""
    language: str = ""


class Description(BaseModel):
    description: str = ""
    description_type: str = ""
    language: str = ""


class Subject(BaseModel):
    subject_name: str = ""
    subject_scheme: str = ""
    scheme_uri: str = ""
    value_uri: str = ""
    classification_code: str = ""


class Date(BaseModel):
    date: str = ""
    date_type: str = ""
    date_information: str = ""


class Language(BaseModel):
    lang_code: str = ""
    description: str = ""
    language: str = ""


class Size(BaseModel):
    size: str = ""
    unit: str = ""


class Collection(BaseModel):
    accrual_method: str = ""
    accrual_periodicity: str = ""
    accrual_policy: str = ""


class MediaFile(BaseModel):
    sizes: list[Size] = []
    physical_carrier: str = ""
    format: str = ""
    variable_measured: str = ""
    checksum: str = ""
    data_quality: str = ""
    measurement_technique: str = ""
    provenance: str = ""
    file_uri: str = ""
    temporal_resolution: str = ""
    Collections: list[Collection] = []


class GeoLocation(BaseModel):
    geo_location_place: str = ""
    geo_location_point: str = ""
    geo_location_box: str = ""
    geo_location_polygon: str = ""
    geo_description: str = ""
    coverage: str = ""


class TemporalEvent(BaseModel):
    start_date: str = ""
    frequency_number: str = ""
    frequency_type: str = ""
    description: str = ""


class FunderIdentifier(BaseModel):
    funder_identifier: str = ""
    funder_identifier_type: str = ""
    scheme_uri: str = ""


class FundingReference(BaseModel):
    funder_name: str = ""
    funding_stream: str = ""
    award_number: str = ""
    award_uri: str = ""
    award_title: str = ""
    funder_identifiers: list[FunderIdentifier] = []


class Right(BaseModel):
    rights: str = ""
    start_date: str = ""
    rights_uri: str = ""
    rights_identifier: str = ""
    rights_identifier_scheme: str = ""
    scheme_uri: str = ""
    rights_condition: str = ""
    rights_holder: str = ""


class AlternateIdentifier(BaseModel):
    alternate_name: str = ""
    alternate_identifier: str = ""
    alternate_identifier_type: str = ""


class RelatedIdentifier(BaseModel):
    related_identifier: str = ""
    related_identifier_type: str = ""
    relation_type: str = ""
    related_metadata_scheme: str = ""
    scheme_uri: str = ""
    scheme_type: str = ""
    resource_type_general: str = ""
    contact: str = ""


class Audience(BaseModel):
    audience: str = ""
    mediator: str = ""
    education_level: str = ""
    instructional_method: str = ""


class Category(BaseModel):
    name: str = ""
    sub_category: str = ""


class Citation(BaseModel):
    title: str = ""
    volume: str = ""
    issue: str = ""
    start_page: str = ""
    end_page: str = ""
    edition: str = ""
    conference_place: str = ""
    conference_date: str = ""


class Resource(BaseModel):
    identifier: str = ""
    identifier_type: str = ""
    editor: str = ""
    maintainer: str = ""
    contact: str = ""
    producer: str = ""
    publication_year: str = ""
    resource_type: str = ""
    resource_type_general: str = ""
    version: str = ""
    thumbnail: str = ""
    language: str = ""


class Attributes(BaseModel):
    resource: Optional[Resource] = None
    alternate_identifiers: list[AlternateIdentifier] = []
    audiences: list[Audience] = []
    categories: list[Category] = []
    citations: list[Citation] = []
    creators: list[Creator] = []
    dates: list[Date] = []
    descriptions: list[Description] = []
    funding_references: list[FundingReference] = []
    geo_locations: list[GeoLocation] = []
    languages: list[Language] = []
    media_files: list[MediaFile] = []
    publishers: list[Publisher] = []
    related_identifiers: list[RelatedIdentifier] = []
    rights: list[Right] = []
    subjects: list[Subject] = []
    temporal_events: list[TemporalEvent] = []
    titles: list[Title] = []


class DataCiteMetadata(BaseModel):
    attributes: Optional[Attributes] = None
