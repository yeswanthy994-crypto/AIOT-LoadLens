/* USER CODE BEGIN Header */
/**
 ******************************************************************************
 * @file           : main.c
 * @brief          : P03 - LoadLens: Fan-Restriction Estimator & Safe Operating Profile
 *                   Target: STM32F446RE (Nucleo-F446RE)
 *                   Sensor: LM35 on PA0 (ADC1_IN0)
 *                   Motor: L298N (PA5 = IN1, PA6 = IN2)
 *                   Display: 16x2 I2C LCD (PB8 = SCL, PB9 = SDA)
 *                   Telemetry: USART2 (PA2=TX, PA3=RX @ 115200 Baud)
 ******************************************************************************
 */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"
#include "adc.h"
#include "i2c.h"
#include "tim.h"
#include "usart.h"
#include "gpio.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include <stdio.h>
#include <string.h>
#include <stdbool.h>
#include "adc.h"
#include "i2c.h"
#include "usart.h"
#include "gpio.h"
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */
typedef enum {
    AIRFLOW_FREE = 0,       // Clean airflow, normal operation
    AIRFLOW_PARTIAL = 1,    // Partially restricted warning
    AIRFLOW_HEAVY = 2       // Heavily restricted, emergency shutdown
} AirflowState_t;
/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
#define LCD_ADDR (0x27 << 1) // Standard I2C address for PCF8574 (use 0x3F << 1 if no response)
/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/

/* USER CODE BEGIN PV */
float baseline_temp = 28.0f;
float current_temp = 28.0f;
float temp_rise = 0.0f;
AirflowState_t current_state = AIRFLOW_FREE;
char lcd_buf[17];
/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
/* USER CODE BEGIN PFP */
float Read_LM35_Temperature(void);
AirflowState_t Classify_Airflow(float delta_t);
void Apply_Safe_Profile(AirflowState_t state);
void Motor_Forward(void);
void Motor_Stop(void);

// I2C LCD Driver functions
void lcd_send_cmd(char cmd);
void lcd_send_data(char data);
void lcd_clear(void);
void lcd_put_cur(int row, int col);
void lcd_send_string(char *str);
void lcd_init(void);
/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */

  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_ADC1_Init();
  MX_I2C1_Init();
  MX_TIM14_Init();
  MX_USART2_UART_Init();
  /* USER CODE BEGIN 2 */
    setbuf(stdout, NULL);

    printf("\r\n=======================================================\r\n");
    printf("   LoadLens P03: Embedded Fan-Restriction Estimator   \r\n");
    printf("   Target: STM32F446RE | Sensor: LM35 on PA0          \r\n");
    printf("   Motor Output: PA5 (IN1), PA6 (IN2)                 \r\n");
    printf("   Display: 16x2 I2C LCD (PB8, PB9)                   \r\n");
    printf("=======================================================\r\n");

    // 1. Initialize LCD Display
    HAL_Delay(100);
    lcd_init();
    lcd_clear();
    lcd_put_cur(0, 0);
    lcd_send_string("LoadLens P03");
    lcd_put_cur(1, 0);
    lcd_send_string("Calibrating...");

    // 2. Startup Buzzer Hardware Self-Test (Beep for 2 seconds)
    HAL_GPIO_WritePin(GPIOB, GPIO_PIN_5, GPIO_PIN_SET);
    HAL_Delay(2000);
    HAL_GPIO_WritePin(GPIOB, GPIO_PIN_5, GPIO_PIN_RESET);

    // 3. Start Motor Spinning Forward
    Motor_Forward();

    // 3. Calibrate Ambient Baseline Temperature
    printf("Calibrating baseline ambient temperature...\r\n");
    float sum_temp = 0.0f;
    for (int i = 0; i < 10; i++) {
        sum_temp += Read_LM35_Temperature();
        HAL_Delay(200);
    }
    baseline_temp = sum_temp / 10.0f;
    printf("Baseline: %d C\r\n", (int)baseline_temp);

    lcd_clear();
  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
    while (1) {
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
        // Step 1: Read LM35 Temperature from PA0 (ADC1_IN0)
        current_temp = Read_LM35_Temperature();

        // Step 2: Calculate temperature rise from starting baseline
        temp_rise = current_temp - baseline_temp;
        if (temp_rise < 0.0f) temp_rise = 0.0f;

        // Step 3: Classify Airflow Restriction State based on 50 deg C threshold
        current_state = Classify_Airflow(current_temp);

        // Step 4: Apply Safe Operating Profile
        Apply_Safe_Profile(current_state);

        // Step 5: Update LCD Display
        const char *state_text = "FREE";
        if (current_state == AIRFLOW_PARTIAL) state_text = "PARTIAL";
        else if (current_state == AIRFLOW_HEAVY) state_text = "HEAVY";

        // Row 1: Temp: XX.X C
        int t_int = (int)current_temp;
        int t_dec = (int)((current_temp - t_int) * 10);
        if (t_dec < 0) t_dec = -t_dec;
        snprintf(lcd_buf, sizeof(lcd_buf), "Temp: %2d.%d C", t_int, t_dec);
        lcd_put_cur(0, 0);
        lcd_send_string(lcd_buf);

        // Row 2: Air : FREE / PARTIAL / HEAVY
        snprintf(lcd_buf, sizeof(lcd_buf), "Air : %-8s", state_text);
        lcd_put_cur(1, 0);
        lcd_send_string(lcd_buf);

        // Step 6: Output live telemetry over USB Serial to PC
        int r_int = (int)temp_rise;
        int r_dec = (int)((temp_rise - r_int) * 10);
        if (r_dec < 0) r_dec = -r_dec;
        int b_int = (int)baseline_temp;
        int b_dec = (int)((baseline_temp - b_int) * 10);
        if (b_dec < 0) b_dec = -b_dec;

        printf("Temp: %2d.%d C | Base: %2d.%d C | Rise: +%2d.%d C | Air: %s\r\n",
               t_int, t_dec, b_int, b_dec, r_int, r_dec, state_text);

        HAL_Delay(500); // 500 ms sampling rate
    }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Configure the main internal regulator output voltage
  */
  __HAL_RCC_PWR_CLK_ENABLE();
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE3);

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSI;
  RCC_OscInitStruct.PLL.PLLM = 16;
  RCC_OscInitStruct.PLL.PLLN = 336;
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV4;
  RCC_OscInitStruct.PLL.PLLQ = 2;
  RCC_OscInitStruct.PLL.PLLR = 2;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV2;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_2) != HAL_OK)
  {
    Error_Handler();
  }
}

/* USER CODE BEGIN 4 */

/**
 * @brief Retarget printf() to USART2
 */
int _write(int file, char *ptr, int len) {
    HAL_UART_Transmit(&huart2, (uint8_t *)ptr, len, HAL_MAX_DELAY);
    return len;
}

/**
 * @brief Spin Motor Forward (D13 = PA5 = HIGH, D12 = PA6 = LOW)
 */
void Motor_Forward(void) {
    HAL_GPIO_WritePin(GPIOA, GPIO_PIN_5, GPIO_PIN_SET);   // D13 (IN1) = HIGH
    HAL_GPIO_WritePin(GPIOA, GPIO_PIN_6, GPIO_PIN_RESET); // D12 (IN2) = LOW
}

/**
 * @brief Stop Motor (D13 = PA5 = LOW, D12 = PA6 = LOW)
 */
void Motor_Stop(void) {
    HAL_GPIO_WritePin(GPIOA, GPIO_PIN_5, GPIO_PIN_RESET); // D13 (IN1) = LOW
    HAL_GPIO_WritePin(GPIOA, GPIO_PIN_6, GPIO_PIN_RESET); // D12 (IN2) = LOW
}

/**
 * @brief Alert Indicator on D4 (PB5)
 */
void Alert_Set(bool on) {
    HAL_GPIO_WritePin(GPIOB, GPIO_PIN_5, on ? GPIO_PIN_SET : GPIO_PIN_RESET);     // D4 (PB5) Buzzer!
    HAL_GPIO_WritePin(GPIOB, LED_ALERT_Pin, on ? GPIO_PIN_SET : GPIO_PIN_RESET);  // PB2
}

/**
 * @brief Read LM35 Temperature from ADC1 Channel 0 (PA0)
 */
float Read_LM35_Temperature(void) {
    uint32_t total = 0;
    for (int i = 0; i < 5; i++) {
        HAL_ADC_Start(&hadc1);
        if (HAL_ADC_PollForConversion(&hadc1, 10) == HAL_OK) {
            total += HAL_ADC_GetValue(&hadc1);
        }
        HAL_ADC_Stop(&hadc1);
        HAL_Delay(2);
    }
    float avg = (float)total / 5.0f;
    float voltage = (avg * 3.3f) / 4095.0f;
    return (voltage * 100.0f);
}

/**
 * @brief Restriction State Classification Logic (Threshold at 50 deg C)
 */
AirflowState_t Classify_Airflow(float temp) {
    if (temp >= 50.0f) {
        return AIRFLOW_HEAVY;     // Temp >= 50 C: MOTOR STOPS
    } else if (temp >= 40.0f) {
        return AIRFLOW_PARTIAL;   // 40 to 49 C: Warning (Motor runs)
    } else {
        return AIRFLOW_FREE;      // < 40 C: Normal (Motor runs)
    }
}

/**
 * @brief Safe Operating-Profile Selector
 */
void Apply_Safe_Profile(AirflowState_t state) {
    if (state == AIRFLOW_HEAVY) {
        // OVERHEAT / RESTRICTION EMERGENCY:
        Motor_Stop();     // STOPS D13 & D12 (0V on both) -> MOTOR FULL STOP!
        Alert_Set(true);  // PB2 Alert ON!
    } else {
        // NORMAL / PARTIAL:
        Motor_Forward();  // D13=HIGH, D12=LOW -> MOTOR SPINS!
        Alert_Set(false); // PB2 Alert OFF!
    }
}

/* ------------------- Robust Auto-Detecting I2C LCD Driver ------------------- */

static uint8_t detected_lcd_addr = 0x4E; // Default 0x27 shifted

static void LCD_WriteNibble(uint8_t nibble, uint8_t rs) {
    uint8_t data = (nibble & 0xF0) | 0x08 | (rs ? 0x01 : 0x00); // Backlight ON
    uint8_t data_en = data | 0x04; // Enable HIGH
    uint8_t data_low = data & ~0x04; // Enable LOW

    HAL_I2C_Master_Transmit(&hi2c1, detected_lcd_addr, &data, 1, 50);
    HAL_Delay(1);
    HAL_I2C_Master_Transmit(&hi2c1, detected_lcd_addr, &data_en, 1, 50);
    HAL_Delay(2);
    HAL_I2C_Master_Transmit(&hi2c1, detected_lcd_addr, &data_low, 1, 50);
    HAL_Delay(1);
}

void lcd_send_cmd(char cmd) {
    LCD_WriteNibble((uint8_t)(cmd & 0xF0), 0);
    LCD_WriteNibble((uint8_t)((cmd << 4) & 0xF0), 0);
    if (cmd == 0x01 || cmd == 0x02) {
        HAL_Delay(3);
    }
}

void lcd_send_data(char data) {
    LCD_WriteNibble((uint8_t)(data & 0xF0), 1);
    LCD_WriteNibble((uint8_t)((data << 4) & 0xF0), 1);
}

void lcd_clear(void) {
    lcd_send_cmd(0x01);
    HAL_Delay(3);
}

void lcd_put_cur(int row, int col) {
    uint8_t addr = (row == 0) ? (0x80 + col) : (0xC0 + col);
    lcd_send_cmd(addr);
}

void lcd_init(void) {
    // 1. Auto-scan I2C to find real LCD address (0x27 or 0x3F)
    detected_lcd_addr = 0x4E; // 0x27 << 1
    if (HAL_I2C_IsDeviceReady(&hi2c1, (0x3F << 1), 2, 20) == HAL_OK) {
        detected_lcd_addr = (0x3F << 1);
    } else if (HAL_I2C_IsDeviceReady(&hi2c1, (0x27 << 1), 2, 20) == HAL_OK) {
        detected_lcd_addr = (0x27 << 1);
    }

    HAL_Delay(100);

    // 2. HD44780 4-bit wakeup sequence
    LCD_WriteNibble(0x30, 0);
    HAL_Delay(10);
    LCD_WriteNibble(0x30, 0);
    HAL_Delay(5);
    LCD_WriteNibble(0x30, 0);
    HAL_Delay(5);
    LCD_WriteNibble(0x20, 0); // Switch to 4-bit mode
    HAL_Delay(5);

    // 3. Display setup commands
    lcd_send_cmd(0x28); // 2 lines, 5x8 matrix
    HAL_Delay(2);
    lcd_send_cmd(0x08); // Display OFF
    HAL_Delay(2);
    lcd_send_cmd(0x01); // Clear Display
    HAL_Delay(5);
    lcd_send_cmd(0x06); // Cursor Increment
    HAL_Delay(2);
    lcd_send_cmd(0x0C); // Display ON, Cursor OFF
    HAL_Delay(5);
}

void lcd_send_string(char *str) {
    while (*str) {
        lcd_send_data(*str++);
    }
}

/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
