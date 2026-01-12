import time
import sys
from loguru import logger
import eospy.cleos
import eospy.keys
from typing import Dict, Any, Optional

# Настройка логера
logger.remove()
logger.add(sys.stderr, format="<white>{time:HH:mm:ss}</white> | <level>{message}</level>")

class WaxClaimer:
    def __init__(self, private_key: str, rpc_url: str = 'https://wax.eos.barcelona'):
        self.rpc_url = rpc_url
        self.cleos = eospy.cleos.Cleos(url=rpc_url)
        self.key = eospy.keys.EOSKey(private_key)
        self.user_account = "" # Сюда нужно передавать имя аккаунта (CLAIMER)

    def set_user(self, account_name: str):
        self.user_account = account_name

    def send_transaction(self, contract: str, action: str, data: Dict[str, Any]):
        """Универсальная функция отправки транзакции"""
        try:
            payload = [{
                'account': contract,
                'name': action,
                'authorization': [{
                    'actor': self.user_account,
                    'permission': 'active',
                }],
                'args': data
            }]

            # Конвертация JSON -> Binary (Самое сложное в EOS/WAX)
            bin_data = self.cleos.abi_json_to_bin(payload[0]['account'], payload[0]['name'], payload[0]['args'])
            payload[0]['data'] = bin_data['binargs']
            payload[0].pop('args') # Убираем сырые аргументы

            trx = {"actions": payload}
            
            # Подписание и отправка
            resp = self.cleos.push_transaction(trx, [self.key])
            
            logger.success(f"Success! TX ID: {resp['transaction_id']}")
            return True

        except Exception as e:
            logger.error(f"Transaction failed: {e}")
            return False

    def claim_drop(self, drop_id: str, amount: str, price: str, mode: int, asset_ids: Optional[list] = None):
        """Логика выбора режима клейма"""
        
        # Конфигурация режимов (чтобы не писать 100 if/else)
        # Формат: (Контракт, Имя метода, Нужны ли asset_ids)
        MODES = {
            1: ('atomicdropsx', 'claimdrop', False),       # Atomic No WL
            2: ('atomicdropsx', 'claimdropwl', False),     # Atomic WL
            3: ('atomicdropsx', 'claimwproof', True),      # Atomic Proof
            4: ('neftyblocksd', 'claimdrop', False),       # Nefty No WL
            5: ('neftyblocksd', 'claimdropwl', False),     # Nefty WL
            6: ('neftyblocksd', 'claimwproof', True)       # Nefty Proof
        }

        if mode not in MODES:
            logger.error("Invalid mode selected")
            return

        contract, action, need_proof = MODES[mode]
        
        # Собираем аргументы
        args = {
            "claimer": self.user_account,
            "drop_id": drop_id,
            "claim_amount": amount,
            "intended_delphi_median": 0,
            "referrer": contract, # Обычно реферер совпадает с платформой или можно ставить свой
            "country": "UA",
            "currency": price
        }

        # NeftyBlocks немного отличается аргументами (там 'amount' вместо 'claim_amount' иногда)
        # Но для унификации оставим базу. Если нужно - можно добавить условие.
        
        if contract == 'neftyblocksd':
             # У Nefty иногда имя поля отличается, надо чекать ABI, но допустим так:
             args['amount'] = args.pop('claim_amount') 

        if need_proof and asset_ids:
            args['asset_ids'] = asset_ids

        logger.info(f"Attempting to claim Drop {drop_id} via {contract} ({action})...")
        self.send_transaction(contract, action, args)

def main():
    # Загрузка конфига (пример)
    try:
        # В реале лучше использовать os.getenv или config.json
        from config import ACC_PK, CLAIMER, DROP_ID, AMOUNT, PRICE, COOLDOWN
    except ImportError:
        logger.error("Config file not found or incomplete!")
        return

    bot = WaxClaimer(private_key=ACC_PK)
    bot.set_user(CLAIMER)

    print('1: Atomic No WL\n2: Atomic WL\n3: Atomic Proof\n4: Nefty No WL\n5: Nefty WL\n6: Nefty Proof')
    try:
        variant = int(input('Choose variant: '))
    except ValueError:
        return

    logger.info("Starting sniper...")
    
    # Бесконечный цикл попыток
    count = 0
    while True:
        success = bot.claim_drop(DROP_ID, AMOUNT, PRICE, variant)
        if not success:
            count += 1
            # logger.info(f"Retrying... ({count})") # Чтобы не спамить в логи
        else:
            break # Выход если успешно, или убери break если нужно много клеймить
        
        time.sleep(COOLDOWN)

if __name__ == "__main__":
    main()