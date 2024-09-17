import logging
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)
import pandas as pd

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Список администраторов (замените на ваш Telegram ID)
SUPER_ADMIN_ID = 136540181  # Ваш реальный Telegram ID
ADMIN_USERS = [SUPER_ADMIN_ID]

def load_prices():
    """Загрузка прайс-листа из файла"""
    df = pd.read_excel('prices.xlsx')
    return df.to_dict('records')

def save_prices(products):
    """Сохранение прайс-листа в файл"""
    df = pd.DataFrame(products)
    df.to_excel('prices.xlsx', index=False)

def get_main_menu_keyboard(user_id):
    """Главное меню для пользователя"""
    buttons = [
        [KeyboardButton("Прайс-лист"), KeyboardButton("Купить")],
        [KeyboardButton("Корзина")]
    ]
    if user_id == SUPER_ADMIN_ID:
        buttons.append([KeyboardButton("Админ-панель")])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def format_price(price):
    """Форматирование цены с разделителем для тысяч."""
    return f"{price:,.0f}".replace(',', ' ')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if 'cart' not in context.user_data:
        context.user_data['cart'] = {}

    # Сохраняем ID пользователя в context.bot_data['all_users']
    all_users = context.bot_data.get('all_users', set())
    all_users.add(user.id)
    context.bot_data['all_users'] = all_users

    keyboard = get_main_menu_keyboard(user.id)
    await update.effective_message.reply_text(
        f"Здравствуйте, {user.first_name}! Добро пожаловать в наш магазин электроники.",
        reply_markup=keyboard
    )

async def handle_menu_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок главного меню."""
    text = update.message.text
    user_id = update.effective_user.id

    # Проверяем, если пользователь не администратор и магазин закрыт
    shop_status = context.bot_data.get('shop_open', True)
    if not shop_status and user_id != SUPER_ADMIN_ID:
        await update.message.reply_text("На данный момент продажи закрыты, пожалуйста, ожидайте старта продаж.")
        return

    # Обработка состояний для ввода данных (если администратор, флаги ввода все еще проверяются)
    if context.user_data.get('awaiting_quantity'):
        await quantity_input(update, context)
        return
    if context.user_data.get('awaiting_quantity_change'):
        await quantity_change_input(update, context)
        return
    if context.user_data.get('awaiting_pavilion_number'):
        await get_pavilion_number(update, context)
        return
    if context.user_data.get('awaiting_new_admin_id'):
        await add_new_admin(update, context)
        return

    # Основное меню
    if text == "Прайс-лист":
        await price_list(update, context)
    elif text == "Купить":
        await menu(update, context)
    elif text == "Корзина":
        await show_cart(update, context)
    elif text == "Админ-панель" and user_id == SUPER_ADMIN_ID:
        await admin_panel(update, context)
    else:
        await update.message.reply_text("Пожалуйста, выберите действие с помощью кнопок.")

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор категорий товаров"""
    products = load_prices()
    categories = set([product['Категория'] for product in products if product['Остаток'] > 0])  # Фильтрация категорий по наличию товаров
    keyboard = [
        [InlineKeyboardButton(category, callback_data=f"category_{category}")]
        for category in categories
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.effective_message.reply_text('Выберите категорию:', reply_markup=reply_markup)

async def category_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ товаров в выбранной категории"""
    query = update.callback_query
    await query.answer()
    category = query.data.split('_', 1)[1]
    products = [p for p in load_prices() if p['Категория'] == category and p['Остаток'] > 0]  # Фильтрация товаров с остатком больше 0
    keyboard = [
        [InlineKeyboardButton(f"{p['Название']} - {format_price(p['Цена'])} руб.", callback_data=f"product_{p['ID']}")]
        for p in products
    ]
    keyboard.append([InlineKeyboardButton("Назад", callback_data="back_to_categories")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(f"Товары в категории '{category}':", reply_markup=reply_markup)

async def product_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор товара и ввод количества"""
    query = update.callback_query
    await query.answer()
    product_id = int(query.data.split('_', 1)[1])
    products = load_prices()
    product = next((item for item in products if item["ID"] == product_id), None)
    if product:
        context.user_data['selected_product'] = product
        await query.message.reply_text(
            f"Введите количество для '{product['Название']}' (в наличии {product['Остаток']} шт.):",
            reply_markup=ReplyKeyboardRemove()
        )
        context.user_data['awaiting_quantity'] = True  # Ожидание ввода количества
        return
    await query.message.reply_text("Товар не найден.", reply_markup=ReplyKeyboardRemove())

async def quantity_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ввода количества при добавлении товара в корзину"""
    quantity_text = update.message.text
    if not quantity_text.isdigit() or int(quantity_text) <= 0:  # Запрет на добавление количества "0" и отрицательных значений
        await update.message.reply_text("Пожалуйста, введите корректное количество, больше нуля.")
        return
    quantity = int(quantity_text)
    product = context.user_data.get('selected_product')
    if not product:
        await update.message.reply_text("Произошла ошибка. Попробуйте снова.")
        return
    if quantity > product['Остаток']:  # Проверка на наличие товара на складе
        await update.message.reply_text(f"Недостаточно товара на складе. В наличии {product['Остаток']} шт.")
        return
    # Резервируем товар
    product['Остаток'] -= quantity
    products = load_prices()
    for p in products:
        if p['ID'] == product['ID']:
            p['Остаток'] = product['Остаток']
            break
    save_prices(products)
    cart = context.user_data.setdefault('cart', {})
    cart_item = cart.get(product['ID'], {'product': product, 'quantity': 0})
    cart_item['quantity'] += quantity
    cart[product['ID']] = cart_item
    await update.message.reply_text(
        f"Добавлено в корзину: {product['Название']} x{quantity} шт."
    )
    keyboard = [
        [
            InlineKeyboardButton("Продолжить покупки", callback_data='continue_shopping'),
            InlineKeyboardButton("Перейти в корзину", callback_data='go_to_cart')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите действие:", reply_markup=reply_markup)

    # Очистить состояние после завершения ввода
    context.user_data.pop('selected_product', None)
    context.user_data.pop('awaiting_quantity', None)

async def continue_shopping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await menu(update, context)

async def go_to_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await show_cart(update, context)

async def show_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отображение корзины"""
    if update.message:
        message = update.message
    elif update.callback_query:
        message = update.callback_query.message
    else:
        return

    cart = context.user_data.get('cart', {})
    if not cart:
        keyboard = get_main_menu_keyboard(update.effective_user.id)
        await message.reply_text("Ваша корзина пуста.", reply_markup=keyboard)
        return

    msg = "Ваша корзина:\n"
    total = 0
    for item in cart.values():
        product = item['product']
        quantity = item['quantity']
        subtotal = product['Цена'] * quantity
        msg += f"- {product['Название']} x{quantity} шт. - {format_price(subtotal)} руб.\n"
        total += subtotal
    msg += f"Итого: {format_price(total)} руб."
    keyboard = [
        [InlineKeyboardButton("Изменить корзину", callback_data='edit_cart')],
        [InlineKeyboardButton("Оформить заказ", callback_data='checkout')],
        [InlineKeyboardButton("Вернуться назад", callback_data='continue_shopping')]  # Возвращаем к покупкам
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await message.reply_text(msg, reply_markup=reply_markup)

async def edit_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("Изменить количество", callback_data='change_quantity')],
        [InlineKeyboardButton("Очистить корзину", callback_data='clear_cart')],
        [InlineKeyboardButton("Назад", callback_data='back_to_cart')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Выберите действие с корзиной:", reply_markup=reply_markup)

async def change_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Изменение количества товара в корзине"""
    query = update.callback_query
    cart = context.user_data.get('cart', {})
    if not cart:
        await query.message.reply_text("Корзина пуста.")
        return

    # Составляем список товаров в корзине
    keyboard = [
        [InlineKeyboardButton(f"{item['product']['Название']} (x{item['quantity']})", callback_data=f"change_item_{item_id}")]
        for item_id, item in cart.items()
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("Выберите товар для изменения количества:", reply_markup=reply_markup)

async def select_item_for_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор товара для изменения количества в корзине"""
    query = update.callback_query
    await query.answer()
    
    # Получаем ID товара из callback_data
    item_id = int(query.data.split('_')[2])
    
    # Сохраняем выбранный товар в user_data
    context.user_data['selected_item_for_change'] = item_id
    await query.message.reply_text("Введите новое количество для выбранного товара:", reply_markup=ReplyKeyboardRemove())
    context.user_data['awaiting_quantity_change'] = True

async def quantity_change_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для изменения количества товара в корзине"""
    quantity_text = update.message.text
    if not quantity_text.isdigit():
        await update.message.reply_text("Пожалуйста, введите корректное количество.")
        return
    quantity = int(quantity_text)
    item_id = context.user_data.get('selected_item_for_change')
    if not item_id or 'cart' not in context.user_data:
        await update.message.reply_text("Произошла ошибка. Попробуйте снова.")
        return

    cart = context.user_data['cart']
    item = cart.get(item_id)
    if not item:
        await update.message.reply_text("Товар не найден в корзине.")
        return
    
    product = item['product']
    
    # Возвращаем на склад текущее количество товара, которое пользователь уже зарезервировал
    available_stock = product['Остаток'] + item['quantity']

    if quantity > available_stock:  # Проверяем, достаточно ли товара на складе после возврата
        await update.message.reply_text(f"Недостаточно товара на складе. В наличии {available_stock} шт.")
        return

    if quantity == 0:  # Удаляем товар из корзины, если введено количество "0"
        # Возвращаем количество товара в корзине обратно на склад
        product['Остаток'] += item['quantity']
        
        del cart[item_id]
        await update.message.reply_text(f"Товар '{product['Название']}' удален из корзины.")
        
        # Сбрасываем флаги ожидания и проверяем, пуста ли корзина
        context.user_data.pop('selected_item_for_change', None)
        context.user_data.pop('awaiting_quantity_change', None)  # Сбрасываем флаг ожидания
        
        # Обновляем прайс-лист
        products = load_prices()
        for p in products:
            if p['ID'] == product['ID']:
                p['Остаток'] = product['Остаток']
                break
        save_prices(products)

        # Если корзина пуста, возвращаем пользователя в главное меню
        if not cart:
            await update.message.reply_text("Корзина пуста.", reply_markup=get_main_menu_keyboard(update.effective_user.id))
        else:
            await show_cart(update, context)  # Если в корзине остались товары, возвращаем пользователя в корзину
        return

    # Обновляем количество товара в корзине и прайс-листе
    old_quantity = item['quantity']
    item['quantity'] = quantity
    product['Остаток'] = available_stock - quantity  # Обновляем остаток на складе после изменения количества

    products = load_prices()
    for p in products:
        if p['ID'] == product['ID']:
            p['Остаток'] = product['Остаток']
            break
    save_prices(products)
    await update.message.reply_text(f"Количество товара '{product['Название']}' изменено на {quantity}.")

    # Очищаем временные данные и возвращаем в корзину
    context.user_data.pop('selected_item_for_change', None)
    context.user_data.pop('awaiting_quantity_change', None)  # Сбрасываем флаг ожидания
    await show_cart(update, context)

async def clear_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Очистить корзину и вернуть товар на склад"""
    cart = context.user_data.get('cart', {})
    products = load_prices()

    # Возвращаем зарезервированные товары на склад
    for item in cart.values():
        for p in products:
            if p['ID'] == item['product']['ID']:
                p['Остаток'] += item['quantity']  # Возвращаем товар на склад
                break
    save_prices(products)

    context.user_data['cart'] = {}
    await update.callback_query.message.reply_text("Корзина очищена.", reply_markup=get_main_menu_keyboard(update.effective_user.id))

async def back_to_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возвращение к просмотру корзины"""
    await show_cart(update, context)

async def price_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ прайс-листа в текстовом или Excel формате"""
    keyboard = [
        [InlineKeyboardButton("Текстовый формат", callback_data='price_text')],
        [InlineKeyboardButton("Excel файл", callback_data='price_excel')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Выберите формат:', reply_markup=reply_markup)

async def send_price_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправка прайс-листа в выбранном формате"""
    query = update.callback_query
    await query.answer()
    choice = query.data

    if choice == 'price_text':
        products = load_prices()
        message = "Прайс-лист:\n"
        
        # Добавляем товары только с положительным остатком
        for product in products:
            if product['Остаток'] > 0:
                message += f"{product['Название']} - {format_price(product['Цена'])} руб. (Остаток: {product['Остаток']})\n"

        if message == "Прайс-лист:\n":  # Если все товары закончились
            message += "Нет доступных товаров."
        
        await query.edit_message_text(text=message)

    elif choice == 'price_excel':
        await query.edit_message_text(text="Отправляем Excel файл...")
        await query.message.reply_document(document=open('prices.xlsx', 'rb'))

async def upload_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if user_id not in ADMIN_USERS:
        await query.message.reply_text("У вас нет прав для выполнения этой команды.")
        return
    await query.message.reply_text("Пожалуйста, отправьте Excel файл с прайс-листом.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка загрузки Excel-файла с прайс-листом"""
    user_id = update.effective_user.id
    if user_id not in ADMIN_USERS:
        await update.message.reply_text("У вас нет прав для загрузки файлов.")
        return
    document = update.message.document
    if document.mime_type != 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
        await update.message.reply_text("Пожалуйста, отправьте файл в формате Excel (.xlsx).")
        return
    file = await context.bot.get_file(document.file_id)
    await file.download_to_drive('prices.xlsx')
    await update.message.reply_text("Прайс-лист успешно обновлен.")
    await start(update, context)  # Возвращаем пользователя в главное меню

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отображение админ-панели"""
    user_id = update.effective_user.id
    if user_id != SUPER_ADMIN_ID:
        if update.message:
            await update.message.reply_text("У вас нет доступа к этой функции.")
        else:
            await update.callback_query.message.reply_text("У вас нет доступа к этой функции.")
        return

    # Проверяем статус магазина
    shop_status = context.bot_data.get('shop_open', True)
    if shop_status:
        shop_button = [InlineKeyboardButton("Закрыть магазин", callback_data='close_shop')]
    else:
        shop_button = [InlineKeyboardButton("Открыть магазин", callback_data='open_shop')]

    keyboard = [
        [InlineKeyboardButton("Добавить администратора", callback_data='add_admin')],
        [InlineKeyboardButton("Удалить администратора", callback_data='remove_admin')],
        [InlineKeyboardButton("Обновить прайс-лист", callback_data='upload_price')],
        shop_button  # Кнопка для открытия/закрытия магазина
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text("Админ-панель:", reply_markup=reply_markup)
    else:
        await update.callback_query.message.reply_text("Админ-панель:", reply_markup=reply_markup)

async def close_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Закрыть магазин - очистить корзины всех пользователей, удалить все сообщения, вернуть остатки на склад и уведомить их"""
    context.bot_data['shop_open'] = False  # Магазин закрыт

    # Загружаем прайс-лист, чтобы вернуть остатки на склад
    products = load_prices()

    # Получаем список всех пользователей
    all_users = context.bot_data.get('all_users', set())

    # Уведомляем всех пользователей о закрытии магазина, очищаем корзины и удаляем все сообщения
    for user_id in all_users:
        # Получаем корзину пользователя
        user_cart = context.user_data.get(user_id, {}).get('cart', {})

        # Если в корзине что-то есть, возвращаем товары на склад
        if user_cart:
            for item in user_cart.values():
                product_id = item['product']['ID']
                quantity = item['quantity']

                # Возвращаем остатки на склад
                for product in products:
                    if product['ID'] == product_id:
                        product['Остаток'] += quantity  # Возвращаем зарезервированное количество на склад
                        break

            # Очищаем корзину пользователя
            context.user_data[user_id]['cart'] = {}

        # Удаляем все предыдущие сообщения бота
        message_ids = context.user_data.get(user_id, {}).get('message_ids', [])
        for message_id in message_ids:
            try:
                await context.bot.delete_message(chat_id=user_id, message_id=message_id)
            except Exception as e:
                logging.error(f"Не удалось удалить сообщение для пользователя {user_id}: {e}")

        # Отправляем уведомление пользователю о закрытии магазина
        try:
            closing_message = await context.bot.send_message(
                chat_id=user_id,
                text="""
===================

ПРИЕМ ЗАКАЗОВ ЗАКРЫТ

===================

Произведен возврат на начальный экран
"""
            )

            # Сохраняем ID этого сообщения, чтобы оставить его единственным в чате
            context.user_data[user_id]['message_ids'] = [closing_message.message_id]
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")

    # Сохраняем обновленный прайс-лист с измененными остатками
    save_prices(products)

    # Уведомляем администратора о том, что магазин закрыт
    await update.callback_query.message.reply_text("Магазин закрыт. Корзины всех пользователей очищены, остатки возвращены на склад.")
    await admin_panel(update, context)  # Вернуть в админ-панель

import os
import sys

async def open_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Открыть магазин - разрешить пользователям доступ к функциям, уведомить их и перезапустить бота"""
    context.bot_data['shop_open'] = True  # Магазин открыт

    # Уведомляем всех пользователей о том, что магазин снова открыт
    all_users = context.bot_data.get('all_users', set())
    for user_id in all_users:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="""
===================

ПРИЕМ ЗАКАЗОВ ОТКРЫТ!

===================
"""
            )
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")

    # Уведомляем администратора о том, что магазин открыт
    await update.callback_query.message.reply_text("Магазин открыт. Перезапуск бота...")

    # Перезапускаем бота
    os.execv(sys.executable, ['python'] + sys.argv)

async def send_message_and_save(update: Update, context: ContextTypes.DEFAULT_TYPE, text):
    """Отправка сообщения пользователю и сохранение его ID"""
    user_id = update.effective_user.id
    message = await context.bot.send_message(chat_id=user_id, text=text)
    
    # Сохраняем ID последнего сообщения
    if 'message_ids' not in context.user_data[user_id]:
        context.user_data[user_id]['message_ids'] = []
    
    context.user_data[user_id]['message_ids'].append(message.message_id)

async def admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data
    if action == 'add_admin':
        context.user_data['awaiting_new_admin_id'] = True
        await query.message.reply_text("Пожалуйста, введите Telegram ID пользователя, которого вы хотите добавить в администраторы:")
    elif action == 'remove_admin':
        user_id = query.from_user.id
        if user_id != SUPER_ADMIN_ID:
            await query.message.reply_text("У вас нет прав для удаления администраторов.")
            return
        admins_to_remove = [admin_id for admin_id in ADMIN_USERS if admin_id != SUPER_ADMIN_ID]
        if not admins_to_remove:
            await query.message.reply_text("Нет администраторов для удаления.")
            return
        keyboard = [
            [InlineKeyboardButton(f"ID: {admin_id}", callback_data=f"confirm_remove_admin_{admin_id}")]
            for admin_id in admins_to_remove
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("Выберите администратора для удаления:", reply_markup=reply_markup)
    elif action == 'upload_price':
        await upload_price(update, context)

async def confirm_remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаление администратора"""
    query = update.callback_query
    await query.answer()
    admin_id = int(query.data.split('_')[-1])
    if admin_id in ADMIN_USERS:
        ADMIN_USERS.remove(admin_id)
        await query.message.reply_text(f"Администратор с ID {admin_id} удален.")
    else:
        await query.message.reply_text("Администратор не найден.")

async def add_new_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавление нового администратора"""
    admin_id_text = update.message.text
    if not admin_id_text.isdigit():
        await update.message.reply_text("Пожалуйста, введите корректный Telegram ID.")
        return
    admin_id = int(admin_id_text)
    if admin_id in ADMIN_USERS:
        await update.message.reply_text("Этот пользователь уже является администратором.")
        return
    ADMIN_USERS.append(admin_id)
    await update.message.reply_text(f"Пользователь с ID {admin_id} добавлен в список администраторов.")
    context.user_data.pop('awaiting_new_admin_id', None)

async def back_to_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат к выбору категории"""
    await menu(update, context)

async def checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("Доставка в ваш павильон", callback_data='delivery_pavilion')],
        [InlineKeyboardButton("Самовывоз", callback_data='delivery_pickup')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Выберите способ доставки:", reply_markup=reply_markup)

async def process_delivery_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # Извлекаем метод доставки из callback_data
    delivery_method = query.data.split('_', 1)[1]

    # Сохраняем метод доставки
    context.user_data['delivery'] = delivery_method
    
    if delivery_method == 'pavilion':
        # Если выбрана доставка в павильон, ожидаем ввод номера павильона
        context.user_data['awaiting_pavilion_number'] = True
        await query.message.reply_text("Пожалуйста, введите номер вашего павильона:", reply_markup=ReplyKeyboardRemove())
    else:
        # Если выбран самовывоз, сразу завершаем заказ
        await finalize_order(update, context)


async def finalize_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершение заказа и отправка информации"""
    cart = context.user_data.get('cart', {})
    methods = {'pavilion': 'Доставка в ваш павильон', 'pickup': 'Самовывоз'}
    delivery_method = context.user_data['delivery']
    
    message = "Ваш заказ:\n"
    total = 0
    for item in cart.values():
        product = item['product']
        quantity = item['quantity']
        subtotal = product['Цена'] * quantity
        message += f"- {product['Название']} x{quantity} шт. - {format_price(subtotal)} руб.\n"
        total += subtotal
    
    message += f"Итого: {format_price(total)} руб.\n"
    message += f"Способ доставки: {methods[delivery_method]}"
    
    # Завершаем заказ
    if update.message:
        await update.message.reply_text("Спасибо за ваш заказ!", reply_markup=get_main_menu_keyboard(update.effective_user.id))
        await update.message.reply_text(message)
    elif update.callback_query:
        await update.callback_query.message.reply_text("Спасибо за ваш заказ!", reply_markup=get_main_menu_keyboard(update.effective_user.id))
        await update.callback_query.message.reply_text(message)

    # Отправляем уведомление администраторам
    admin_message = f"Новый заказ от {update.effective_user.first_name} (@{update.effective_user.username}):\n{message}"
    for admin_id in ADMIN_USERS:
        await context.bot.send_message(chat_id=admin_id, text=admin_message)

    # Очищаем данные о корзине, доставке и сбрасываем флаги ожидания ввода
    context.user_data['cart'] = {}
    context.user_data.pop('delivery', None)
    context.user_data.pop('pavilion_number', None)
    context.user_data.pop('awaiting_quantity', None)  # Сброс флага ожидания количества
    context.user_data.pop('awaiting_quantity_change', None)  # Сброс флага ожидания изменения количества

async def get_pavilion_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода номера павильона и завершение заказа"""
    pavilion_number = update.message.text
    context.user_data['pavilion_number'] = pavilion_number  # Сохраняем номер павильона
    context.user_data.pop('awaiting_pavilion_number', None)  # Сбрасываем ожидание ввода номера павильона
    await finalize_order(update, context)  # Завершаем заказ



def main():
    application = Application.builder().token("7115351510:AAEe4iRCWY57BlPLnSeutR_7eNbY8OMcFE0").build()

    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu))
    application.add_handler(CommandHandler("cart", show_cart))
    application.add_handler(CommandHandler("pricelist", price_list))
    application.add_handler(CommandHandler("upload_price", upload_price))

    # Обработчики текстовых сообщений (кнопки главного меню и ввод данных)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_button))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))  # Обработчик документов

    # Обработчики CallbackQuery
    application.add_handler(CallbackQueryHandler(category_selection, pattern='^category_'))
    application.add_handler(CallbackQueryHandler(product_selection, pattern='^product_'))
    application.add_handler(CallbackQueryHandler(change_quantity, pattern='^change_quantity$'))
    application.add_handler(CallbackQueryHandler(select_item_for_change, pattern='^change_item_'))
    application.add_handler(CallbackQueryHandler(clear_cart, pattern='^clear_cart$'))
    application.add_handler(CallbackQueryHandler(back_to_cart, pattern='^back_to_cart$'))
    application.add_handler(CallbackQueryHandler(continue_shopping, pattern='^continue_shopping$'))
    application.add_handler(CallbackQueryHandler(close_shop, pattern='^close_shop$'))
    application.add_handler(CallbackQueryHandler(open_shop, pattern='^open_shop$'))
    application.add_handler(CallbackQueryHandler(edit_cart, pattern='^edit_cart$'))
    application.add_handler(CallbackQueryHandler(checkout, pattern='^checkout$'))
    application.add_handler(CallbackQueryHandler(go_to_cart, pattern='^go_to_cart$'))
    application.add_handler(CallbackQueryHandler(send_price_list, pattern='^(price_text|price_excel)$'))
    application.add_handler(CallbackQueryHandler(process_delivery_choice, pattern='^delivery_'))
    application.add_handler(CallbackQueryHandler(admin_action, pattern='^(add_admin|remove_admin|upload_price)$'))
    application.add_handler(CallbackQueryHandler(confirm_remove_admin, pattern='^confirm_remove_admin_'))
    application.add_handler(CallbackQueryHandler(back_to_categories, pattern='^back_to_categories$'))

    application.run_polling()

if __name__ == '__main__':
    main()
