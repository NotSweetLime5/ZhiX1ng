"""Opt-in live checks of the image built from deployments/sandbox.Dockerfile."""

import asyncio
import os

import pytest

from app.core.config import Settings
from app.services.tools import Tools

pytestmark = pytest.mark.skipif(
    os.getenv("ZHIXING_TEST_SANDBOX") != "1", reason="Set ZHIXING_TEST_SANDBOX=1 after building the sandbox image"
)


@pytest.mark.parametrize(
    ("language", "code"),
    [
        ("python", "print(2+3)"),
        ("shell", 'printf "5\\n"'),
        ("go", "package main\nfunc main(){println(2+3)}"),
    ],
)
async def test_user_code_executes_inside_restricted_container(language, code):
    tools = Tools(None, None, Settings(sandbox_enabled=True))
    result = await asyncio.to_thread(tools.sandbox, {"language": language, "code": code})
    assert result["exit_code"] == 0 and result["output"].strip() == "5", result
