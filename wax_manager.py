import sys
import time
import requests
from typing import List, Dict

import eospy.cleos
import eospy.keys
from loguru import logger

# Настройка логера
logger.remove()
logger.add(sys.stderr, format="<white>{time:HH:mm:ss}</white> | <level>{message}</level>")

class WaxManager:
    def __init__(self, private_key: str, user_account: str, rpc_url: str = 'https://wax.eos.barcelona'):
        self.cleos = eospy.cleos.Cleos(url=rpc_url)
        self.key = eospy.keys.EOSKey(private_key)
        self.user_account = user_account
        self.atomic_api = "https://wax.api.atomicassets.io/atomicassets/v1/assets"

    def get_wax_balance(self) -> float:
        """Получаем баланс WAX напрямую из блокчейна (без Selenium!)"""
        try:
            # Запрос к смарт-контракту eosio.token
            balance = self.cleos.get_currency_balance('eosio.token', self.user_account, 'WAX')
            if balance:
                # balance возвращается как ["100.00000000 WAX"]
                return float(balance[0].split()[0])
            return 0.0
        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
            return 0.0

    def get_nfts(self) -> List[str]:
        """Получаем список ID всех NFT на кошельке через Atomic API"""
        try:
            params = {
                "owner": self.user_account,
                "limit": "100", # Можно увеличить
                "order": "desc",
                "sort": "asset_id"
            }
            resp = requests.get(self.atomic_api, params=params)
            data = resp.json()
            
            if data['success']:
                # Возвращаем список ID
                return [asset['asset_id'] for asset in data['data']]
            return []
        except Exception as e:
            logger.error(f"Failed to fetch NFTs: {e}")
            return []

    def _push_tx(self, contract: str, action: str, data: Dict):
        """Внутренняя функция отправки (как в Снайпере)"""
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

            bin_data = self.cleos.abi_json_to_bin(payload[0]['account'], payload[0]['name'], payload[0]['args'])
            payload[0]['data'] = bin_data['binargs']
            payload[0].pop('args')

            trx = {"actions": payload}
            resp = self.cleos.push_transaction(trx, [self.key])
            logger.success(f"TX: {resp['transaction_id']}")
            return True
        except Exception as e:
            logger.error(f"TX Error: {e}")
            return False

    def transfer_wax(self, to_account: str, amount: float, memo: str = ""):
        """Отправка токенов"""
        # Форматируем сумму под стандарт WAX (8 знаков после запятой)
        quantity = "{:.8f} WAX".format(amount)
        logger.info(f"Sending {quantity} to {to_account}...")
        
        data = {
            "from": self.user_account,
            "to": to_account,
            "quantity": quantity,
            "memo": memo
        }
        return self._push_tx("eosio.token", "transfer", data)

    def transfer_nft(self, to_account: str, asset_ids: List[str], memo: str = ""):
        """Отправка NFT (AtomicAssets)"""
        logger.info(f"Sending {len(asset_ids)} NFTs to {to_account}...")
        
        data = {
            "from": self.user_account,
            "to": to_account,
            "asset_ids": asset_ids,
            "memo": memo
        }
        return self._push_tx("atomicassets", "transfer", data)

def main():
    # Фейковые данные для теста (Замени на загрузку из конфига!)
    MY_ACCOUNT = "mywaxwallet1"
    DESTINATION = "epaba.wam" # Твой кошелек из скрипта
    # PRIVATE_KEY взять из config
    
    # Инициализация (заглушка ключа для примера)
    manager = WaxManager("5K...Private...Key", MY_ACCOUNT)

    print("1: Sweep WAX (Send all tokens)")
    print("2: Sweep NFTs (Send all NFTs)")
    
    choice = input("Select: ")

    if choice == "1":
        bal = manager.get_wax_balance()
        logger.info(f"Current Balance: {bal} WAX")
        if bal > 0:
            amount = float(input(f"How much to send? (Max: {bal}): "))
            manager.transfer_wax(DESTINATION, amount)
    
    elif choice == "2":
        logger.info("Scanning for NFTs...")
        nfts = manager.get_nfts()
        logger.info(f"Found {len(nfts)} NFTs")
        
        if nfts:
            confirm = input("Send ALL NFTs? (y/n): ")
            if confirm.lower() == 'y':
                # Атомик позволяет отправлять пачкой
                manager.transfer_nft(DESTINATION, nfts)

if __name__ == "__main__":
    main()