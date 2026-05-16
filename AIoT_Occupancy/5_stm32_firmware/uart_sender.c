/*
 * ============================================================================
 * FILE: uart_sender.c  (NO WiFi — USB Serial only)
 * Board: B-L4S5I-IOT01A
 * STM32CubeIDE 1.19.0
 * ============================================================================
 *
 * PURPOSE:
 *   Reads VL53L0X ToF sensor via I2C2 and prints the distance via USART1
 *   (redirected to USB Virtual COM Port via ST-Link).
 *   Python server.py reads COM4 and runs AI inference.
 *
 * HOW TO USE:
 *   1. Open your VL53L0X_ToF_Interfacing project in STM32CubeIDE
 *   2. Copy each /* PASTE INTO ... section into the matching USER CODE block
 *   3. Build & Flash (F11)
 *   4. Open Device Manager → check which COM port appears (e.g. COM4)
 *   5. Run:  uvicorn server:app --host 0.0.0.0 --port 8000 --reload
 *
 * OUTPUT FORMAT (one line per second):
 *   DIST:423
 *   DIST:418
 *   DIST:1850
 *
 * CubeMX SETTINGS NEEDED (only I2C2 + USART1 — no SPI, no WiFi):
 *   - I2C2:   Fast Mode 400 kHz, SCL=PB10, SDA=PB11
 *   - USART1: Async 115200, TX=PB6, RX=PB7  (ST-Link VCP)
 *   - PC6:    GPIO Output (XSHUT for VL53L0X)
 * ============================================================================
 */


/* ─────────────────────────────────────────────────────────────────────────────
 * PASTE INTO: USER CODE BEGIN Includes
 * ─────────────────────────────────────────────────────────────────────────── */
#include "vl53l0x_api.h"
#include <stdio.h>
#include <string.h>


/* ─────────────────────────────────────────────────────────────────────────────
 * PASTE INTO: USER CODE BEGIN PV
 * ─────────────────────────────────────────────────────────────────────────── */
VL53L0X_Dev_t                    mySensor;
VL53L0X_RangingMeasurementData_t rangingData;
VL53L0X_Error                    tofStatus;
uint16_t                         distanceMM;
uint32_t                         refSpadCount;
uint8_t                          isApertureSpads;
uint8_t                          vhvSettings;
uint8_t                          phaseCal;

/* printf re-route to USART1 (add this function anywhere in USER CODE BEGIN 0) */
/*
int __io_putchar(int ch) {
    HAL_UART_Transmit(&huart1, (uint8_t *)&ch, 1, 100);
    return ch;
}
*/


/* ─────────────────────────────────────────────────────────────────────────────
 * PASTE INTO: USER CODE BEGIN 0
 * ─────────────────────────────────────────────────────────────────────────── */

/* Redirect printf → USART1 (Virtual COM Port / ST-Link) */
int __io_putchar(int ch) {
    HAL_UART_Transmit(&huart1, (uint8_t *)&ch, 1, 100);
    return ch;
}


/* ─────────────────────────────────────────────────────────────────────────────
 * PASTE INTO: USER CODE BEGIN 2  (after all MX_xxx_Init() calls)
 * ─────────────────────────────────────────────────────────────────────────── */

HAL_Delay(500);
printf("\r\n=== AIoT Occupancy Detection - Serial Mode ===\r\n");
printf("Board : B-L4S5I-IOT01A\r\n");
printf("Sensor: VL53L0X ToF via I2C2\r\n");
printf("Output: DIST:<mm> at 115200 baud\r\n");
printf("================================================\r\n\r\n");

/* --- XSHUT: reset the VL53L0X sensor (PC6) --- */
HAL_GPIO_WritePin(GPIOC, GPIO_PIN_6, GPIO_PIN_RESET);
HAL_Delay(10);
HAL_GPIO_WritePin(GPIOC, GPIO_PIN_6, GPIO_PIN_SET);
HAL_Delay(10);

/* --- VL53L0X Initialization --- */
mySensor.I2cHandle  = &hi2c2;
mySensor.I2cDevAddr = 0x52;   /* default 7-bit address */

tofStatus = VL53L0X_DataInit(&mySensor);
if (tofStatus != VL53L0X_ERROR_NONE) {
    printf("[ERROR] VL53L0X_DataInit failed: %d\r\n", tofStatus);
    printf("        Check: SDA=PB11, SCL=PB10, XSHUT=PC6\r\n");
}

tofStatus = VL53L0X_StaticInit(&mySensor);
tofStatus = VL53L0X_PerformRefCalibration(&mySensor, &vhvSettings, &phaseCal);
tofStatus = VL53L0X_PerformRefSpadManagement(&mySensor, &refSpadCount, &isApertureSpads);
tofStatus = VL53L0X_SetDeviceMode(&mySensor, VL53L0X_DEVICEMODE_SINGLE_RANGING);

/* High accuracy mode */
VL53L0X_SetLimitCheckEnable(&mySensor, VL53L0X_CHECKENABLE_SIGMA_FINAL_RANGE, 1);
VL53L0X_SetLimitCheckEnable(&mySensor, VL53L0X_CHECKENABLE_SIGNAL_RATE_FINAL_RANGE, 1);
VL53L0X_SetLimitCheckValue(&mySensor, VL53L0X_CHECKENABLE_SIGNAL_RATE_FINAL_RANGE,
                            (FixPoint1616_t)(0.25 * 65536));
VL53L0X_SetLimitCheckValue(&mySensor, VL53L0X_CHECKENABLE_SIGMA_FINAL_RANGE,
                            (FixPoint1616_t)(18 * 65536));
VL53L0X_SetMeasurementTimingBudgetMicroSeconds(&mySensor, 200000);

printf("[OK] VL53L0X ready — starting distance stream\r\n\r\n");


/* ─────────────────────────────────────────────────────────────────────────────
 * PASTE INTO: USER CODE BEGIN 3  (inside while(1) loop)
 * ─────────────────────────────────────────────────────────────────────────── */

tofStatus = VL53L0X_PerformSingleRangingMeasurement(&mySensor, &rangingData);

if (tofStatus == VL53L0X_ERROR_NONE && rangingData.RangeStatus == 0) {
    distanceMM = rangingData.RangeMilliMeter;

    /*
     * Print in format that server.py expects:
     *   DIST:423
     */
    printf("DIST:%u\r\n", distanceMM);

} else {
    /* Sensor error — print debug but server.py will ignore non-DIST lines */
    printf("[WARN] RangeStatus=%d  tofStatus=%d\r\n",
           rangingData.RangeStatus, tofStatus);
}

HAL_Delay(1000);   /* 1 Hz — increase if you want faster sampling */


/*
 * ============================================================================
 * COMPLETE main.c REFERENCE (just the USER CODE sections filled in)
 * ============================================================================
 *
 * int main(void)
 * {
 *   // USER CODE BEGIN 1  (empty)
 *
 *   HAL_Init();
 *   SystemClock_Config();
 *   MX_GPIO_Init();
 *   MX_I2C2_Init();
 *   MX_USART1_UART_Init();
 *
 *   // USER CODE BEGIN 2
 *   [PASTE SECTION 3 HERE]
 *   // USER CODE END 2
 *
 *   while (1)
 *   {
 *     // USER CODE BEGIN 3
 *     [PASTE SECTION 4 HERE]
 *     // USER CODE END 3
 *   }
 * }
 *
 * ============================================================================
 * TROUBLESHOOTING
 * ============================================================================
 *
 * No output in terminal:
 *   - Check USART1 is enabled in CubeMX (TX=PB6, RX=PB7, 115200 baud)
 *   - Confirm __io_putchar() is defined in USER CODE BEGIN 0
 *   - Check correct COM port in Device Manager (look for STMicroelectronics)
 *
 * "VL53L0X_DataInit failed":
 *   - Verify I2C2: SCL=PB10, SDA=PB11, speed=400kHz
 *   - Check XSHUT wire to PC6 (GPIO Output, init LOW then HIGH)
 *
 * server.py says "FAILED to open COM4":
 *   - Run GET http://localhost:8000/com/ports to see available ports
 *   - Change DEFAULT_COM_PORT in server.py to match your board's port
 *
 * RangeStatus != 0 (e.g. 4):
 *   - Sensor out of range or signal too weak
 *   - Ensure pointing at a surface within 2m
 *   - Status 4 = phase fail (target too close, < 30mm)
 * ============================================================================
 */
