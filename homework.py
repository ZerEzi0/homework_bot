import logging
import os
import sys
import time
from http import HTTPStatus

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


def check_tokens() -> bool:
    """
    Проверяет доступность переменных окружения.

    Возвращает:
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
            f"Отсутствуют обязательные переменные окружения: "
            f"{', '.join(missing_tokens)}"
        )
        return False
    return True


def send_message(bot: telebot.TeleBot, message: str) -> None:
    """
    Отправляет сообщение в Telegram.

    Args:
        bot (telebot.TeleBot): Экземпляр бота.
        message (str): Текст сообщения.

    Raises:
        Exception: Если не удалось отправить сообщение.
    """
    try:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
        logger.debug(f'Бот отправил сообщение: "{message}"')
    except Exception as error:
        logger.error(f'Не удалось отправить сообщение в Telegram: {error}')
        raise


def get_api_answer(timestamp: int) -> dict:
    """
    Делает запрос к API Практикум Домашка.

    Args:
        timestamp (int): Временная метка для запроса.

    Returns:
        dict: Ответ API в формате Python-словаря.

    Raises:
        Exception: В случае неуспешного запроса.
    """
    params = {'from_date': timestamp}
    try:
        response = requests.get(ENDPOINT, headers=HEADERS, params=params)
        if response.status_code != HTTPStatus.OK:
            raise Exception(
                f'Эндпоинт {ENDPOINT} недоступен. '
                f'Код ответа API: {response.status_code}'
            )
        return response.json()
    except requests.RequestException as error:
        raise Exception(f'Ошибка при запросе к API: {error}')


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
    if not isinstance(response, dict):
        raise TypeError('Ответ API не является словарём.')

    if 'homeworks' not in response:
        raise KeyError("В ответе API отсутствует ключ 'homeworks'.")

    homeworks = response['homeworks']
    if not isinstance(homeworks, list):
        raise TypeError("'homeworks' в ответе API не является списком.")

    return homeworks


def parse_status(homework: dict) -> str:
    """
    Извлекает статус домашней работы и возвращает сообщение.

    Args:
        homework (dict): Словарь с информацией о домашней работе.

    Returns:
        str: Сообщение для отправки в Telegram.

    Raises:
        Exception: Если в данных домашней работы отсутствуют необходимые ключи
                   или статус неизвестен.
    """
    if 'status' not in homework:
        raise Exception("В ответе API отсутствует ключ 'status'.")

    if 'homework_name' not in homework:
        raise Exception("В ответе API отсутствует ключ 'homework_name'.")

    status = homework['status']
    homework_name = homework['homework_name']

    if status not in HOMEWORK_VERDICTS:
        raise Exception(f"Неизвестный статус домашней работы: {status}")

    verdict = HOMEWORK_VERDICTS[status]
    return f'Изменился статус проверки работы "{homework_name}". {verdict}'


def main():
    """Основная логика работы бота."""
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
                for homework in homeworks:
                    message = parse_status(homework)
                    send_message(bot, message)
                timestamp = response.get('current_date', timestamp)
            else:
                logger.debug('Новых статусов нет.')

            last_error = None

        except Exception as error:
            message = f'Сбой в работе программы: {error}'
            logger.error(message)
            if last_error != str(error):
                try:
                    send_message(bot, message)
                except Exception as telegram_error:
                    logger.error(
                        f'Не удалось отправить сообщение об ошибке: '
                        f'{telegram_error}'
                    )
                last_error = str(error)

        finally:
            time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    main()
