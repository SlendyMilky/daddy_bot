from aiogram import Dispatcher
from aiogram.enums import UpdateType

from daddy_bot.modules.admin import router as admin_router
from daddy_bot.modules.auto_triggers import router as auto_triggers_router
from daddy_bot.modules.bibine import router as bibine_router
from daddy_bot.modules.f_respects import router as f_respects_router
from daddy_bot.modules.fun import router as fun_router
from daddy_bot.modules.help import router as help_router
from daddy_bot.modules.social_stub import router as social_stub_router
from daddy_bot.modules.start import router as start_router
from daddy_bot.modules.utility import router as utility_router


def register_routers(dp: Dispatcher) -> None:
    dp.include_router(admin_router)
    dp.include_router(start_router)
    dp.include_router(help_router)
    dp.include_router(fun_router)
    dp.include_router(f_respects_router)
    dp.include_router(bibine_router)
    dp.include_router(utility_router)
    dp.include_router(social_stub_router)
    dp.include_router(auto_triggers_router)
