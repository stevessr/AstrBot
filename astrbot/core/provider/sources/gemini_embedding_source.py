import asyncio
import time
from typing import cast

from google import genai
from google.genai import types
from google.genai.errors import APIError

from astrbot import logger

from ..entities import ProviderType
from ..provider import EmbeddingProvider, RemoteBatchFailedError
from ..register import register_provider_adapter


@register_provider_adapter(
    "gemini_embedding",
    "Google Gemini Embedding 提供商适配器",
    provider_type=ProviderType.EMBEDDING,
)
class GeminiEmbeddingProvider(EmbeddingProvider):
    def __init__(self, provider_config: dict, provider_settings: dict) -> None:
        super().__init__(provider_config, provider_settings)
        self.provider_config = provider_config
        self.provider_settings = provider_settings

        api_key: str = provider_config["embedding_api_key"]
        api_base: str = provider_config["embedding_api_base"]
        timeout: int = int(provider_config.get("timeout", 20))

        http_options = types.HttpOptions(timeout=timeout * 1000)
        if api_base:
            api_base = api_base.removesuffix("/")
            http_options.base_url = api_base
        proxy = provider_config.get("proxy", "")
        if proxy:
            http_options.async_client_args = {"proxy": proxy}
            logger.info(f"[Gemini Embedding] 使用代理: {proxy}")

        self.client = genai.Client(api_key=api_key, http_options=http_options).aio

        self.model = provider_config.get(
            "embedding_model",
            "gemini-embedding-exp-03-07",
        )
        self.batch_poll_interval = float(provider_config.get("batch_poll_interval", 5))
        self.batch_timeout = float(provider_config.get("batch_timeout", 300))

    def supports_remote_batch(self) -> bool:
        return True

    async def _run_remote_batch_job(
        self,
        texts: list[str],
        progress_callback=None,
    ) -> list[list[float]]:
        await self._emit_embedding_progress(
            progress_callback, 0, len(texts), "batching"
        )
        try:
            job = await self.client.batches.create_embeddings(
                model=self.model,
                src={
                    "inlined_requests": {
                        "contents": texts,
                        "config": {
                            "output_dimensionality": self.get_dim(),
                        },
                    }
                },
                config={"display_name": "AstrBot embedding batch"},
            )
        except Exception as e:
            raise RemoteBatchFailedError(f"提交 Gemini Batch 失败: {e}") from e

        await self._emit_embedding_progress(progress_callback, 1, 1, "batching")

        started_at = time.monotonic()
        while not job.done:
            if time.monotonic() - started_at > self.batch_timeout:
                raise RemoteBatchFailedError(
                    f"Gemini Batch 超时，job={job.name}, timeout={self.batch_timeout}s"
                )
            await self._emit_embedding_progress(
                progress_callback, 0, 1, "batch_waiting"
            )
            await asyncio.sleep(self.batch_poll_interval)
            try:
                job = await self.client.batches.get(name=job.name)
            except Exception as e:
                raise RemoteBatchFailedError(f"查询 Gemini Batch 状态失败: {e}") from e

        state_name = job.state.name if job.state else "UNKNOWN"
        if state_name != "JOB_STATE_SUCCEEDED":
            raise RemoteBatchFailedError(
                f"Gemini Batch 执行失败，state={state_name}, error={job.error}"
            )

        responses = (
            job.dest.inlined_embed_content_responses
            if job.dest and job.dest.inlined_embed_content_responses
            else None
        )
        if not responses or len(responses) != len(texts):
            raise RemoteBatchFailedError(
                f"Gemini Batch 返回结果数量异常: expected={len(texts)}, actual={len(responses) if responses else 0}"
            )

        embeddings: list[list[float]] = []
        for response in responses:
            if response.error:
                raise RemoteBatchFailedError(
                    f"Gemini Batch 子请求失败: {response.error}"
                )
            if (
                not response.response
                or not response.response.embedding
                or response.response.embedding.values is None
            ):
                raise RemoteBatchFailedError("Gemini Batch 返回了空 embedding")
            embeddings.append(response.response.embedding.values)

        await self._emit_embedding_progress(
            progress_callback, len(texts), len(texts), "batch_waiting"
        )
        return embeddings

    async def get_embedding(self, text: str) -> list[float]:
        """获取文本的嵌入"""
        try:
            result = await self.client.models.embed_content(
                model=self.model,
                contents=text,
                config=types.EmbedContentConfig(
                    output_dimensionality=self.get_dim(),
                ),
            )
            assert result.embeddings is not None
            assert result.embeddings[0].values is not None
            return result.embeddings[0].values
        except APIError as e:
            raise Exception(f"Gemini Embedding API请求失败: {e.message}") from e

    async def get_embeddings(self, text: list[str]) -> list[list[float]]:
        """批量获取文本的嵌入"""
        try:
            result = await self.client.models.embed_content(
                model=self.model,
                contents=cast(types.ContentListUnion, text),
                config=types.EmbedContentConfig(
                    output_dimensionality=self.get_dim(),
                ),
            )
            assert result.embeddings is not None

            embeddings: list[list[float]] = []
            for embedding in result.embeddings:
                assert embedding.values is not None
                embeddings.append(embedding.values)
            return embeddings
        except APIError as e:
            raise Exception(f"Gemini Embedding API批量请求失败: {e.message}") from e

    def get_dim(self) -> int:
        """获取向量的维度"""
        return int(self.provider_config.get("embedding_dimensions", 768))

    async def terminate(self):
        if self.client:
            await self.client.aclose()
