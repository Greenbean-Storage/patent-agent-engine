from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    S3_BUCKET: str
    AWS_REGION: str = "ap-northeast-2"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()  # type: ignore[reportCallIssue]
