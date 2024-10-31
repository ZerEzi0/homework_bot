import logging
import os
import sys
import time
from http import HTTPStatus
from contextlib import suppress

import requests
import telebot
from dotenv import load_dotenv

load_dotenv()

PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

RETRY_PERIOD = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}

HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.'
}

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)

formatter = logging.Formatter(
    '%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
handler.setFormatter(formatter)
logger.addHandler(handler)


class BotException(Exception):
    """Базовое исключение для бота."""

    pass


class TelegramSendMessageError(BotException):
    """Исключение при ошибке отправки сообщения в Telegram."""

    pass


def check_tokens() -> bool:
    """
    Проверяет доступность переменных окружения.

    Returns:
        bool: True, если все токены доступны, иначе False.
    """
    tokens = {
        'PRACTICUM_TOKEN': PRACTICUM_TOKEN,
        'TELEGRAM_TOKEN': TELEGRAM_TOKEN,
        'TELEGRAM_CHAT_ID': TELEGRAM_CHAT_ID
    }
    missing_tokens = [token for token, value in tokens.items() if not value]
    if missing_tokens:
        logger.critical(
            "Отсутствуют обязательные переменные окружения: "
            f"{', '.join(missing_tokens)}"
        )
        return False
    logger.debug("Все необходимые переменные окружения доступны.")
    return True


def send_message(bot: telebot.TeleBot, message: str) -> None:
    """
    Отправляет сообщение в Telegram.

    Args:
        bot (telebot.TeleBot): Экземпляр бота.
        message (str): Текст сообщения.

    Raises:
        TelegramSendMessageError: Если не удалось отправить сообщение.
    """
    logger.debug(f"Попытка отправить сообщение: '{message}'")
    try:
        bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=message
        )
        logger.info(f"Бот успешно отправил сообщение: '{message}'")
    except (
        telebot.apihelper.ApiException,
        requests.RequestException
    ) as error:
        raise TelegramSendMessageError(
            f"Ошибка отправки сообщения в Telegram: {error}"
        )


def get_api_answer(timestamp: int) -> dict:
    """
    Делает запрос к API Практикум Домашка.

    Args:
        timestamp (int): Временная метка для запроса.

    Returns:
        dict: Ответ API в формате Python-словаря.

    Raises:
        ConnectionError: Если не удалось подключиться к API.
        ValueError: Если ответ API имеет неверный статус
        или некорректный формат.
    """
    params = {'from_date': timestamp}
    logger.debug(f"Отправка запроса к API: {ENDPOINT} с параметрами {params}")
    try:
        response = requests.get(
            ENDPOINT,
            headers=HEADERS,
            params=params,
            timeout=10
        )
        logger.debug(
            f"Получен ответ от API: статус {response.status_code} - "
            f"{response.reason}"
        )
    except requests.RequestException as error:
        raise ConnectionError(f"Ошибка при запросе к API: {error}")

    if response.status_code != HTTPStatus.OK:
        raise ValueError(
            f"Эндпоинт {ENDPOINT} недоступен. "
            f"Код ответа API: {response.status_code} - {response.reason}"
        )

    return response.json()


def check_response(response: dict) -> list:
    """
    Проверяет ответ API на соответствие документации.

    Args:
        response (dict): Ответ API.

    Returns:
        list: Список домашних работ.

    Raises:
        KeyError: Если в ответе отсутствует ключ 'homeworks'.
        TypeError: Если значение под ключом 'homeworks' не является списком.
    """
    logger.debug("Проверка структуры ответа API.")
    if not isinstance(response, dict):
        raise TypeError(f"Ожидался словарь, получен {type(response)}.")

    if 'homeworks' not in response:
        raise KeyError("В ответе API отсутствует ключ 'homeworks'.")

    homeworks = response['homeworks']
    if not isinstance(homeworks, list):
        raise TypeError(
            f"'homeworks' должен быть списком, получен {type(homeworks)}."
        )

    logger.debug(f"Количество домашних работ в ответе: {len(homeworks)}")
    return homeworks


def parse_status(homework: dict) -> str:
    """
    Извлекает статус домашней работы и возвращает сообщение.

    Args:
        homework (dict): Словарь с информацией о домашней работе.

    Returns:
        str: Сообщение для отправки в Telegram.

    Raises:
        KeyError: Если в данных домашней работы отсутствуют необходимые ключи.
        ValueError: Если статус работы неизвестен.
    """
    logger.debug("Анализ статуса домашней работы.")
    required_keys = ['status', 'homework_name']
    for key in required_keys:
        if key not in homework:
            raise KeyError(
                f"В данных домашней работы отсутствует ключ '{key}'."
            )

    status = homework['status']
    homework_name = homework['homework_name']

    if status not in HOMEWORK_VERDICTS:
        raise ValueError(f"Неизвестный статус домашней работы: {status}")

    verdict = HOMEWORK_VERDICTS[status]
    message = f'Изменился статус проверки работы "{homework_name}". {verdict}'
    logger.debug(f"Сформировано сообщение: '{message}'")
    return message


def main():
    """
    Основная логика работы бота.

    Бот выполняет следующие действия:
    1. Проверяет наличие необходимых токенов.
    2. Запускает бесконечный цикл, в котором:
       - Делает запрос к API Практикума домашка.
       - Проверяет ответ API.
       - Парсит статус домашней работы.
       - Отправляет сообщение в Telegram.
       - Обрабатывает и логирует исключения.
    """
    if not check_tokens():
        sys.exit('Отсутствуют необходимые переменные окружения.')

    bot = telebot.TeleBot(token=TELEGRAM_TOKEN)
    timestamp = int(time.time())
    last_error = None

    while True:
        try:
            response = get_api_answer(timestamp)
            homeworks = check_response(response)

            if homeworks:
                homework = homeworks[0]
                message = parse_status(homework)
                send_message(bot, message)
            else:
                logger.debug('Новых статусов нет.')

            timestamp = response.get('current_date', int(time.time()))
            last_error = None

        except TelegramSendMessageError as error:
            logger.error(f"Ошибка отправки сообщения в Telegram: {error}")
        except Exception as error:
            message = f'Сбой в работе программы: {error}'
            logger.error(message)
            if last_error != message:
                with suppress(TelegramSendMessageError):
                    send_message(bot, message)
                last_error = message
        finally:
            time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    main()
