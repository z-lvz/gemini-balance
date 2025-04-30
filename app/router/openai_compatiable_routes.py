from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.config.config import settings
from app.core.security import SecurityService
from app.domain.openai_models import (
    ChatRequest,
    EmbeddingRequest,
    ImageGenerationRequest,
)
from app.handler.retry_handler import RetryHandler
from app.log.logger import get_openai_compatible_logger
from app.service.key.key_manager import KeyManager, get_key_manager_instance
from app.service.openai_compatiable_service import OpenAICompatiableService


router = APIRouter()
logger = get_openai_compatible_logger()

# 初始化服务
security_service = SecurityService()

async def get_key_manager():
    return await get_key_manager_instance()


async def get_next_working_key_wrapper(
    key_manager: KeyManager = Depends(get_key_manager),
):
    return await key_manager.get_next_working_key()


async def get_openai_service(key_manager: KeyManager = Depends(get_key_manager)):
    """获取OpenAI聊天服务实例"""
    return OpenAICompatiableService(settings.BASE_URL, key_manager)


@router.get("/openai/v1/models")
async def list_models(
    _=Depends(security_service.verify_authorization),
    key_manager: KeyManager = Depends(get_key_manager),
    openai_service: OpenAICompatiableService = Depends(get_openai_service),
):
    logger.info("-" * 50 + "list_models" + "-" * 50)
    logger.info("Handling models list request")
    api_key = await key_manager.get_first_valid_key()
    logger.info(f"Using API key: {api_key}")
    try:
        return await openai_service.get_models(api_key)
    except Exception as e:
        logger.error(f"Error getting models list: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Internal server error while fetching models list"
        ) from e


@router.post("/openai/v1/chat/completions")
@RetryHandler(max_retries=settings.MAX_RETRIES, key_arg="api_key")
async def chat_completion(
    request: ChatRequest,
    _=Depends(security_service.verify_authorization),
    api_key: str = Depends(get_next_working_key_wrapper),
    key_manager: KeyManager = Depends(get_key_manager),
    openai_service: OpenAICompatiableService = Depends(get_openai_service),
):
    # 如果model是imagen3,使用paid_key
    if request.model == f"{settings.CREATE_IMAGE_MODEL}-chat":
        api_key = await key_manager.get_paid_key()
    logger.info("-" * 50 + "chat_completion" + "-" * 50)
    logger.info(f"Handling chat completion request for model: {request.model}")
    logger.debug(f"Request: \n{request.model_dump_json(indent=2)}")
    logger.info(f"Using API key: {api_key}")

    try:
        # 如果model是imagen3,使用paid_key
        if request.model == f"{settings.CREATE_IMAGE_MODEL}-chat":
            response = await openai_service.create_image_chat_completion(request, api_key)
        else:
            response = await openai_service.create_chat_completion(request, api_key)
        # 处理流式响应
        if request.stream:
            return StreamingResponse(response, media_type="text/event-stream")
        logger.info("Chat completion request successful")
        return response
    except Exception as e:
        logger.error(f"Chat completion failed after retries: {str(e)}")
        raise HTTPException(status_code=500, detail="Chat completion failed") from e


@router.post("/openai/v1/images/generations")
async def generate_image(
    request: ImageGenerationRequest,
    _=Depends(security_service.verify_authorization),
    openai_service: OpenAICompatiableService = Depends(get_openai_service),
):
    logger.info("-" * 50 + "generate_image" + "-" * 50)
    logger.info(f"Handling image generation request for prompt: {request.prompt}")
    request.model = settings.CREATE_IMAGE_MODEL

    try:
        response = await openai_service.generate_images(request)
        logger.info("Image generation request successful")
        return response
    except Exception as e:
        logger.error(f"Image generation request failed: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Image generation request failed"
        ) from e


@router.post("/openai/v1/embeddings")
async def embedding(
    request: EmbeddingRequest,
    _=Depends(security_service.verify_authorization),
    key_manager: KeyManager = Depends(get_key_manager),
    openai_service: OpenAICompatiableService = Depends(get_openai_service),
):
    logger.info("-" * 50 + "embedding" + "-" * 50)
    logger.info(f"Handling embedding request for model: {request.model}")
    api_key = await key_manager.get_next_working_key()
    logger.info(f"Using API key: {api_key}")
    try:
        response = await openai_service.create_embeddings(
            input_text=request.input, model=request.model, api_key=api_key
        )
        logger.info("Embedding request successful")
        return response
    except Exception as e:
        logger.error(f"Embedding request failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Embedding request failed") from e
