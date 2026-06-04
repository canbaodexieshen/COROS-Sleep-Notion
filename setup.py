from setuptools import setup, find_packages

setup(
    name="coros-sleep-notion",
    version="1.0.0",
    description="自动将 COROS 高驰手表的睡眠数据同步到 Notion",
    author="Your Name",
    packages=find_packages(),
    python_requires=">=3.11",
    install_requires=[
        "httpx>=0.25.0",
        "pydantic>=2.0.0",
        "pycryptodome>=3.19.0",
        "python-dotenv>=1.0.0",
        "notion-client>=2.0.0",
    ],
    entry_points={
        "console_scripts": [
            "coros-sync=src.main:main",
        ],
    },
)
