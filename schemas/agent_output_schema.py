"""Agent output schemas for typed DSPy signatures."""

from pydantic import BaseModel, Field
from typing import Optional


class TitleOutput(BaseModel):
    name: str = Field(description="The title text")
    title_type: str = Field(
        default="MainTitle", description="MainTitle, AlternativeTitle, or Subtitle"
    )
    language: str = Field(default="", description="ISO 639-1 language code")


class DescriptionOutput(BaseModel):
    description: str = Field(description="The description text")
    description_type: str = Field(
        default="Abstract", description="Abstract, Summary, Methods, or Other"
    )
    language: str = Field(default="", description="ISO 639-1 language code")


class LanguageOutput(BaseModel):
    lang_code: str = Field(description="ISO 639-1 language code (e.g., 'es', 'en')")
    language: str = Field(default="", description="Full language name")
    description: str = Field(default="", description="Optional description")


class ResourceOutput(BaseModel):
    identifier: str = Field(default="", description="DOI, URL, or other identifier")
    identifier_type: str = Field(default="", description="DOI, URL, URI, etc.")
    publication_year: str = Field(default="", description="Year of publication (YYYY)")
    resource_type: str = Field(default="", description="Dataset, Software, Text, etc.")
    resource_type_general: str = Field(default="", description="General resource type")
    language: str = Field(default="", description="ISO 639-1 language code")


class ExplorerOutput(BaseModel):
    titles: list[TitleOutput] = Field(default_factory=list)
    descriptions: list[DescriptionOutput] = Field(default_factory=list)
    languages: list[LanguageOutput] = Field(default_factory=list)
    resource: Optional[ResourceOutput] = None


class NameIdentifierOutput(BaseModel):
    name_identifier: str = Field(default="", description="ORCID, ROR, ISNI, etc.")
    name_identifier_scheme: str = Field(default="", description="ORCID, ROR, ISNI")
    scheme_uri: str = Field(default="", description="URI of the scheme")


class AffiliationOutput(BaseModel):
    affiliation: str = Field(default="", description="Affiliation name")
    affiliation_identifier: str = Field(default="", description="ROR or other ID")
    affiliation_identifier_scheme: str = Field(default="", description="ROR, etc.")


class CreatorOutput(BaseModel):
    creator_name: str = Field(description="Full name or organization name")
    creator_name_type: str = Field(
        default="Organizational", description="Personal or Organizational"
    )
    given_name: str = Field(default="", description="First name for persons")
    family_name: str = Field(default="", description="Last name for persons")
    type: str = Field(default="Organization", description="Person or Organization")
    name_identifiers: list[NameIdentifierOutput] = Field(default_factory=list)
    affiliations: list[AffiliationOutput] = Field(default_factory=list)


class PublisherOutput(BaseModel):
    publisher_name: str = Field(description="Publisher name")
    publisher_identifier: str = Field(default="", description="ROR or DOI")
    publisher_identifier_scheme: str = Field(
        default="", description="ROR, DOI, Crossref"
    )
    publisher_scheme_uri: str = Field(default="", description="Scheme URI")


class CreatorPublisherOutput(BaseModel):
    creators: list[CreatorOutput] = Field(default_factory=list)
    publishers: list[PublisherOutput] = Field(default_factory=list)


class SubjectItem(BaseModel):
    subject_name: str = Field(description="Subject keyword or term")
    subject_scheme: str = Field(default="", description="LCSH, MeSH, DDC, etc.")
    scheme_uri: str = Field(default="", description="URI of the subject scheme")
    value_uri: str = Field(default="", description="URI to the specific term")
    classification_code: str = Field(default="", description="Classification code")


class SubjectOutput(BaseModel):
    subjects: list[SubjectItem] = Field(default_factory=list)


class DateOutput(BaseModel):
    date: str = Field(description="Date in ISO 8601 format (YYYY-MM-DD or YYYY)")
    date_type: str = Field(
        default="Issued",
        description="Accepted, Available, Copyrighted, Collected, Created, Issued, Submitted, Updated, Valid",
    )
    date_information: str = Field(
        default="", description="Description of what this date represents"
    )


class TemporalEventOutput(BaseModel):
    start_date: str = Field(default="", description="Start date in ISO 8601 format")
    frequency_number: str = Field(default="", description="Frequency number")
    frequency_type: str = Field(
        default="", description="daily, weekly, monthly, yearly"
    )
    description: str = Field(
        default="", description="Description of the temporal event"
    )


class GeoLocationOutput(BaseModel):
    geo_location_place: str = Field(
        default="", description="Place name (e.g., 'Chile')"
    )
    geo_location_point: str = Field(
        default="", description="Point coordinates (lat, lon)"
    )
    geo_location_box: str = Field(
        default="", description="Bounding box (south,west,north,east)"
    )
    geo_location_polygon: str = Field(default="", description="Polygon coordinates")
    geo_description: str = Field(
        default="", description="Description of geographic coverage"
    )
    coverage: str = Field(default="", description="Spatial coverage description")


class TemporalGeoOutput(BaseModel):
    dates: list[DateOutput] = Field(default_factory=list)
    temporal_events: list[TemporalEventOutput] = Field(default_factory=list)
    geo_locations: list[GeoLocationOutput] = Field(default_factory=list)


class SizeOutput(BaseModel):
    size: str = Field(default="", description="File size number")
    unit: str = Field(default="", description="bytes, KB, MB, GB")


class MediaFileOutput(BaseModel):
    sizes: list[SizeOutput] = Field(default_factory=list)
    physical_carrier: str = Field(default="", description="digital or physical")
    format: str = Field(
        default="", description="IANA media type (application/json, text/csv)"
    )
    variable_measured: str = Field(default="", description="What the data measures")
    checksum: str = Field(default="", description="MD5 or SHA256 checksum")
    data_quality: str = Field(default="", description="Quality notes")
    measurement_technique: str = Field(default="", description="How data was collected")
    provenance: str = Field(default="", description="Data source or origin")
    file_uri: str = Field(default="", description="Direct download URL")
    temporal_resolution: str = Field(
        default="", description="ISO 8601 duration (P1D, P1M, P1Y)"
    )


class MediaFilesOutput(BaseModel):
    media_files: list[MediaFileOutput] = Field(default_factory=list)


class RightOutput(BaseModel):
    rights: str = Field(default="", description="Rights statement")
    start_date: str = Field(default="", description="Start date of rights")
    rights_uri: str = Field(default="", description="URI to rights statement")
    rights_identifier: str = Field(default="", description="Rights identifier")
    rights_identifier_scheme: str = Field(default="", description="SPDX, etc.")
    scheme_uri: str = Field(default="", description="Scheme URI")
    rights_condition: str = Field(default="", description="Conditions of use")
    rights_holder: str = Field(default="", description="Rights holder name")


class RightsOutput(BaseModel):
    rights: list[RightOutput] = Field(default_factory=list)


class FunderIdentifierOutput(BaseModel):
    funder_identifier: str = Field(default="", description="Funder ID")
    funder_identifier_type: str = Field(
        default="", description="Crossref Funder ID, ISNI, ROR"
    )
    scheme_uri: str = Field(default="", description="Scheme URI")


class FundingReferenceOutput(BaseModel):
    funder_name: str = Field(default="", description="Funder name")
    funding_stream: str = Field(default="", description="Funding stream")
    award_number: str = Field(default="", description="Award number")
    award_uri: str = Field(default="", description="Award URI")
    award_title: str = Field(default="", description="Award title")
    funder_identifiers: list[FunderIdentifierOutput] = Field(default_factory=list)


class FundingOutput(BaseModel):
    funding_references: list[FundingReferenceOutput] = Field(default_factory=list)


class RelatedIdentifierOutput(BaseModel):
    related_identifier: str = Field(default="", description="Related identifier")
    related_identifier_type: str = Field(default="", description="DOI, URL, ISBN, etc.")
    relation_type: str = Field(
        default="", description="IsCitedBy, Cites, IsSupplementTo, etc."
    )
    related_metadata_scheme: str = Field(default="", description="Metadata scheme")
    scheme_uri: str = Field(default="", description="Scheme URI")
    scheme_type: str = Field(default="", description="Scheme type")
    resource_type_general: str = Field(
        default="", description="Dataset, Software, etc."
    )
    contact: str = Field(default="", description="Contact info")


class RelatedIdentifiersOutput(BaseModel):
    related_identifiers: list[RelatedIdentifierOutput] = Field(default_factory=list)


class AlternateIdentifierOutput(BaseModel):
    alternate_name: str = Field(default="", description="Alternate name")
    alternate_identifier: str = Field(default="", description="Alternate identifier")
    alternate_identifier_type: str = Field(default="", description="Type of identifier")


class AlternateIdentifiersOutput(BaseModel):
    alternate_identifiers: list[AlternateIdentifierOutput] = Field(default_factory=list)


class AudienceOutput(BaseModel):
    audience: str = Field(default="", description="Target audience")
    mediator: str = Field(default="", description="Mediator")
    education_level: str = Field(default="", description="Education level")
    instructional_method: str = Field(default="", description="Instructional method")


class AudiencesOutput(BaseModel):
    audiences: list[AudienceOutput] = Field(default_factory=list)


class CategoryOutput(BaseModel):
    name: str = Field(default="", description="Category name")
    sub_category: str = Field(default="", description="Sub-category")


class CategoriesOutput(BaseModel):
    categories: list[CategoryOutput] = Field(default_factory=list)


class CitationOutput(BaseModel):
    title: str = Field(default="", description="Citation title")
    volume: str = Field(default="", description="Volume")
    issue: str = Field(default="", description="Issue")
    start_page: str = Field(default="", description="Start page")
    end_page: str = Field(default="", description="End page")
    edition: str = Field(default="", description="Edition")
    conference_place: str = Field(default="", description="Conference place")
    conference_date: str = Field(default="", description="Conference date")


class CitationsOutput(BaseModel):
    citations: list[CitationOutput] = Field(default_factory=list)
