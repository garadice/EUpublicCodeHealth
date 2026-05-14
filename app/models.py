from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Boolean, Integer, BigInteger, DateTime, Text, ForeignKey, func


class Base(DeclarativeBase):
    pass


class CatalogSource(Base):
    __tablename__ = "catalog_sources"
    source_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    url: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Project(Base):
    __tablename__ = "projects"
    project_id: Mapped[str] = mapped_column(String, primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("catalog_sources.source_id"))
    name: Mapped[str] = mapped_column(String)
    repo_url_raw: Mapped[str | None] = mapped_column(Text)
    license: Mapped[str | None] = mapped_column(String)


class Repository(Base):
    __tablename__ = "repositories"
    repository_id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"))
    host: Mapped[str] = mapped_column(String)
    owner: Mapped[str | None] = mapped_column(String)
    repo_name: Mapped[str | None] = mapped_column(String)
    repo_url_canonical: Mapped[str | None] = mapped_column(Text)


class RepoMetric(Base):
    __tablename__ = "repository_metrics_snapshots"
    snapshot_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.repository_id"))
    observed_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    pushed_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    archived: Mapped[bool | None] = mapped_column(Boolean)
    stars: Mapped[int | None] = mapped_column(Integer)
    forks: Mapped[int | None] = mapped_column(Integer)
    open_issues: Mapped[int | None] = mapped_column(Integer)
    default_branch: Mapped[str | None] = mapped_column(String)
