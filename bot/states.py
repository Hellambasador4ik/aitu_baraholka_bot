from aiogram.fsm.state import State, StatesGroup


class SubmitAd(StatesGroup):
    category = State()
    text = State()
    photos = State()
    contact = State()
