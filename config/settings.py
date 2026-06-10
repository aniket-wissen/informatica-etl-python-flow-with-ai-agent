from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    DB_ENGINE:    str = "postgresql"
    DB_HOST:      Optional[str] = None
    DB_PORT:      Optional[int] = None
    DB_NAME:      Optional[str] = None
    DB_USER:      Optional[str] = None
    DB_PASSWORD:  Optional[str] = None
    GROQ_API_KEY: str

    @property
    def database_url(self) -> str:
        from urllib.parse import quote_plus
        engine = self.DB_ENGINE.lower()

        if engine == "sqlite":
            return f"sqlite:///data/{self.DB_NAME or 'financial_etl'}.db"

        if engine == "postgresql":
            return (
                f"postgresql+psycopg2://"
                f"{self.DB_USER}:{quote_plus(self.DB_PASSWORD)}"
                f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            )

        if engine == "mssql":
            return (
                f"mssql+pyodbc://"
                f"{self.DB_USER}:{quote_plus(self.DB_PASSWORD)}"
                f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
                f"?driver=ODBC+Driver+18+for+SQL+Server"
                f"&TrustServerCertificate=yes"
            )

        raise ValueError(f"Unsupported DB_ENGINE: {engine}")

    class Config:
        env_file = ".env"


settings = Settings()