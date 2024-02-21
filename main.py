from flask import Flask, render_template
import threading
from binance.client import Client
import time
import logging
from binance.exceptions import BinanceAPIException
import configparser
from flask import Flask, render_template, jsonify

app = Flask(__name__)

class BinanceOrderBookScanner:
    def __init__(self, api_key, api_secret, symbols, threshold=100000, interval=60, min_percentage_to_density=1):
        # Initialize the scanner object with parameters
        self.client = Client(api_key, api_secret)
        self.symbols = symbols
        self.threshold = threshold
        self.interval = interval
        self.min_percentage_to_density = min_percentage_to_density
        self.large_limit_orders = {}  # Dictionary to store information about large limit orders
        self.processed_orders = set()
        self.logger = self.setup_logger()

    def setup_logger(self):
        # Setup logger for recording events
        logger = logging.getLogger("BinanceOrderBookScanner")
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s [%(levelname)s]: %(message)s')

        file_handler = logging.FileHandler('binance_scanner.log')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        return logger

    def get_current_price(self, symbol):
        try:
            # Get the current price for the given symbol
            ticker = self.client.get_ticker(symbol=symbol)
            return float(ticker['lastPrice'])
        except BinanceAPIException as e:
            self.logger.error(f"Binance API Exception: {e}")
            return None

    def calculate_decay_time(self, symbol, threshold):
        # Calculate decay time for the given symbol and threshold value
        order_book = self.client.get_order_book(symbol=symbol)
        total_density = sum(float(bid[0]) * float(bid[1]) for bid in order_book['bids'])
        trade_volume_15min = self.get_15min_trade_volume(symbol)

        decay_time = total_density / trade_volume_15min if trade_volume_15min != 0 else float('inf')
        return decay_time

    def calculate_percentage_to_density(self, symbol, price_large_limit):
        # Calculate percentage to density for the given symbol and price of large limit
        current_price = self.get_current_price(symbol)
        if current_price is None:
            return None

        percentage_to_density = ((current_price - price_large_limit) / current_price) * 100
        return percentage_to_density

    def get_15min_trade_volume(self, symbol):
        # Get trade volume for the last 15 minutes for the given symbol
        end_time = int(time.time() * 1000)
        start_time = end_time - 15 * 60 * 1000

        try:
            klines = self.client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_15MINUTE,
                                            startTime=start_time, endTime=end_time)
            return sum(float(kline[5]) for kline in klines)
        except BinanceAPIException as e:
            self.logger.error(f"Binance API Exception: {e}")
            return 0

    def scan_order_book(self, symbol, threshold):
        start_time = time.time()
        decay_time = self.calculate_decay_time(symbol, threshold)

        try:
            order_book = self.client.get_order_book(symbol=symbol)
        except BinanceAPIException as e:
            self.logger.error(f"Binance API Exception: {e}")
            return

        for bid in order_book['bids']:
            price, quantity = float(bid[0]), float(bid[1])
            total_value = int( price * quantity)

            if total_value > threshold and (symbol, price, quantity, 'buy') not in self.processed_orders:
                percentage_to_density =float( self.calculate_percentage_to_density(symbol, price))

                if symbol not in self.large_limit_orders and percentage_to_density <= self.min_percentage_to_density:
                    self.large_limit_orders[symbol] = {
                        'market_type': 'Spot',
                        'action': 'Long',
                        'price': price,
                        'quantity': quantity,
                        'total_value': total_value,
                        'decay_time': decay_time,
                        'percentage_to_density': percentage_to_density,
                        'elapsed_time': time.time() - start_time,
                        '15min_volume_trade':self.get_15min_trade_volume(symbol)
                    }

        for ask in order_book['asks']:
            price, quantity = float(ask[0]), float(ask[1])
            total_value = int(price * quantity)

            if total_value > threshold and (symbol, price, quantity, 'sell') not in self.processed_orders:
                percentage_to_density = float(self.calculate_percentage_to_density(symbol, price))

                if symbol not in self.large_limit_orders and percentage_to_density <= self.min_percentage_to_density:
                    self.large_limit_orders[symbol] = {
                        'market_type': 'Spot',
                        'action': 'Short',
                        'price': price,
                        'quantity': quantity,
                        'total_value': total_value,
                        'decay_time': decay_time,
                        'percentage_to_density': percentage_to_density,
                        'elapsed_time': time.time() - start_time,
                        '15min_volume_trade': self.get_15min_trade_volume(symbol)

                    }

    def scan_futures_order_book(self, symbol, threshold):
        start_time = time.time()
        decay_time = self.calculate_decay_time(symbol, threshold)

        try:
            order_book = self.client.futures_order_book(symbol=symbol)
        except BinanceAPIException as e:
            self.logger.error(f"Binance API Exception: {e}")
            return

        for bid in order_book['bids']:
            price, quantity = float(bid[0]), float(bid[1])
            total_value = int(price * quantity)

            if total_value > threshold and (symbol, price, quantity, 'buy') not in self.processed_orders:
                percentage_to_density = float(self.calculate_percentage_to_density(symbol, price))

                if symbol not in self.large_limit_orders and percentage_to_density <= self.min_percentage_to_density:
                    self.large_limit_orders[symbol] = {
                        'market_type': 'Futures',
                        'action': 'Long',
                        'price': price,
                        'quantity': quantity,
                        'total_value': total_value,
                        'decay_time': decay_time,
                        'percentage_to_density': percentage_to_density,
                        'elapsed_time': time.time() - start_time,
                        '15min_volume_trade': self.get_15min_trade_volume(symbol)

                    }

        for ask in order_book['asks']:
            price, quantity = float(ask[0]), float(ask[1])
            total_value = int(price * quantity)

            if total_value > threshold and (symbol, price, quantity, 'sell') not in self.processed_orders:
                percentage_to_density = float(self.calculate_percentage_to_density(symbol, price))

                if symbol not in self.large_limit_orders and percentage_to_density >= self.min_percentage_to_density:
                    self.large_limit_orders[symbol] = {
                        'market_type': 'Futures',
                        'action': 'Short',
                        'price': price,
                        'quantity': quantity,
                        'total_value': total_value,
                        'decay_time': decay_time,
                        'percentage_to_density': percentage_to_density,
                        'elapsed_time': time.time() - start_time,
                        '15min_volume_trade': self.get_15min_trade_volume(symbol)

                    }

    def get_large_limit_orders(self):
        # Get information about large limit orders
        return self.large_limit_orders

    def log_large_limit_order(self, symbol):
        # Log information about a large limit order
        order_details = self.large_limit_orders[symbol]
        self.logger.info(
                f"Symbol: {symbol}, Type: {order_details['market_type']}, Action: {order_details['action']}, "
                f"Price: {order_details['price']:.5f}, Quantity: {order_details['quantity']}, "
                f"Total Value: {order_details['total_value']}, Decay Time: {order_details['decay_time']:.2f} minutes, "
                f"Percentage to Density: {order_details['percentage_to_density']:.2f}%, "
                f"Time in Book: {order_details['elapsed_time']:.2f} minutes")

@app.route('/')
def index():
    # Display data on the main page
    large_limit_orders = scanner.get_large_limit_orders()
    return render_template('index.html', large_limit_orders=large_limit_orders)

@app.route('/data')
def get_data():
    large_limit_orders = scanner.get_large_limit_orders()
    return jsonify(large_limit_orders)
def read_config():
    # Read configuration data from the file
    config = configparser.ConfigParser()
    config.read('config.ini')
    api_key = config.get('Credentials', 'api_key')
    api_secret = config.get('Credentials', 'api_secret')
    symbols = config.get('Settings', 'symbols').split(',')
    return api_key, api_secret, symbols

def start_scanner(scanner):
    # Run the scanner in a separate thread
    while True:
        for symbol in scanner.symbols:
            try:
                scanner.scan_order_book(symbol, scanner.threshold)
                scanner.scan_futures_order_book(symbol, scanner.threshold)
            except Exception as e:
                scanner.logger.error(f"An unexpected error occurred: {e}")

        for symbol in scanner.large_limit_orders:
            scanner.log_large_limit_order(symbol)

        #time.sleep(scanner.interval)
        scanner.processed_orders.clear()
        scanner.large_limit_orders = {}

if __name__ == "__main__":
    # Initialize the scanner and run the Flask application
    api_key, api_secret, symbols = read_config()
    threshold = 130000
    interval = 60
    min_percentage_to_density = 1

    scanner = BinanceOrderBookScanner(api_key, api_secret, symbols, threshold, interval, min_percentage_to_density)

    scanner_thread = threading.Thread(target=start_scanner, args=(scanner,))
    scanner_thread.start()

    app.run(debug=True)
