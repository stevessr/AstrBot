import asyncio
import logging
import shutil
import sys

logger = logging.getLogger("astrbot")


class UvInstaller:
    def __init__(self, uv_install_arg: str, pypi_index_url: str | None = None):
        self.uv_install_arg = uv_install_arg
        self.pypi_index_url = pypi_index_url

        # 检查 uv 是否安装
        if not shutil.which("uv"):
            logger.warning("未找到 uv 命令，将回退到 pip 安装方式")
            self.use_uv = False
        else:
            self.use_uv = True

    async def install(
        self,
        package: str | None = None,
        requirements_path: str | None = None,
        mirror: str | None = None,
    ):
        if not self.use_uv:
            # 回退到 pip 安装方式
            return await self._install_with_pip(package, requirements_path, mirror)

        args = ["pip", "install"]
        if package:
            args.extend(package.split())
        elif requirements_path:
            args.extend(["-r", requirements_path])

        index_url = mirror or self.pypi_index_url or "https://pypi.org/simple"

        args.extend(["--index-url", index_url])

        if self.uv_install_arg:
            args.extend(self.uv_install_arg.split())

        logger.info(f"UV 包管理器: uv {' '.join(args)}")
        try:
            process = await asyncio.create_subprocess_exec(
                "uv",
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            assert process.stdout is not None
            async for line in process.stdout:
                logger.info(line.decode().strip())

            await process.wait()

            if process.returncode != 0:
                raise Exception(f"安装失败，错误码：{process.returncode}")
        except FileNotFoundError:
            # uv 命令不存在，回退到 pip
            logger.warning("uv 命令不存在，回退到 pip 安装方式")
            self.use_uv = False
            return await self._install_with_pip(package, requirements_path, mirror)
        except Exception as e:
            logger.error(f"uv 安装失败: {e}")
            # 回退到 pip 安装方式
            return await self._install_with_pip(package, requirements_path, mirror)

    async def _install_with_pip(
        self,
        package: str | None = None,
        requirements_path: str | None = None,
        mirror: str | None = None,
    ):
        """使用 pip 安装包（回退方案）"""
        args = ["install"]
        if package:
            args.append(package)
        elif requirements_path:
            args.extend(["-r", requirements_path])

        index_url = mirror or self.pypi_index_url or "https://pypi.org/simple"

        args.extend(["--trusted-host", "mirrors.aliyun.com", "-i", index_url])

        if self.uv_install_arg:
            args.extend(self.uv_install_arg.split())

        logger.info(f"Pip 包管理器: pip {' '.join(args)}")
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "pip",
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            assert process.stdout is not None
            async for line in process.stdout:
                logger.info(line.decode().strip())

            await process.wait()

            if process.returncode != 0:
                raise Exception(f"安装失败，错误码：{process.returncode}")
        except FileNotFoundError:
            # 没有 pip
            from pip import main as pip_main

            result_code = await asyncio.to_thread(pip_main, args)

            # 清除 pip.main 导致的多余的 logging handlers
            for handler in logging.root.handlers[:]:
                logging.root.removeHandler(handler)

            if result_code != 0:
                raise Exception(f"安装失败，错误码：{result_code}")
