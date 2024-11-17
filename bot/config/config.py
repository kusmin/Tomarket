from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True)

    API_ID: int
    API_HASH: str

    REF_ID: str = '0001b3Lf'
    
    FAKE_USERAGENT: bool = False
    POINTS_COUNT: list[int] = [350, 400]
    AUTO_PLAY_GAME: bool = True
    AUTO_TASK: bool = True
    AUTO_DAILY_REWARD: bool = True
    AUTO_CLAIM_STARS: bool = True
    AUTO_CLAIM_COMBO: bool = True
    AUTO_RANK_UPGRADE: bool = True
    AUTO_RAFFLE: bool = True
    AUTO_CHANGE_NAME: bool = True
    AUTO_ADD_WALLET: bool = False
    PLAY_RANDOM_GAME: bool = True
    PLAY_RANDOM_GAME_COUNT: list[int] = [3, 7]
    NIGHT_SLEEP: bool = True   #strongly recommend to enable this
    NIGHT_SLEEP_TIME: list[list] = [[21 , 23],[2 , 4]] # 10,11pm to 3,4am

    USE_RANDOM_DELAY_IN_RUN: bool = True
    RANDOM_DELAY_IN_RUN: list[int] = [0, 15]

    USE_PROXY_FROM_FILE: bool = False


settings = Settings()

