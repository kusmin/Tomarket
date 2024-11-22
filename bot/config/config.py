from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_ignore_empty=True)

    API_ID: int
    API_HASH: str

    REF_ID: str = '000059BV'
    
    FAKE_USERAGENT: bool = False
    POINTS_COUNT: list[int] = [380, 420]
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
    NIGHT_SLEEP_TIME: list[list] = [[21 , 23],[2 , 4]] # 9,11pm to 2,4am
    AUTO_AIRDROP_TASK: bool = True
    AUTO_CLAIM_AIRDROP: bool = True
    
    AUTO_CONVERT_TOMA: bool = True
    MIN_BALANCE_BEFORE_CONVERT: list[int] = [30000, 100000] # balance must reach between 30k to 100k toma before it will start converting

    USE_RANDOM_DELAY_IN_RUN: bool = True
    RANDOM_DELAY_IN_RUN: list[int] = [0, 15]

    USE_PROXY_FROM_FILE: bool = False


settings = Settings()

