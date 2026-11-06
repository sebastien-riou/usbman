# Real world trials with Managed Hub

## Managed Hub not connected:
USB topology:
usb1: xHCI Host Controller [subtree=500mA, 480M]
`-- 1-1: Integrated_Webcam_FHD [500mA, bus-pwr, 480M]
usb3: xHCI Host Controller [subtree=200mA, 480M]
|-- 3-3: 58200 [100mA, self-pwr, 480M]
`-- 3-4: Wireless_Device [100mA, self-pwr, 480M]
usb7: xHCI Host Controller [subtree=100mA, 480M]
`-- 7-1: USB2.1 Hub [0mA, self-pwr, subtree=100mA, 480M]
    `-- 7-1.4: HID Device [100mA, self-pwr, 480M]



## Managed Hub connected
We connect a USB mouse to the enabled channel to see it

### all off
(pqsign) sru@riou-sebastien-pqshield:~/repos/pqsign$ ./tools/usb-power-check 
USB topology:
usb1: xHCI Host Controller [subtree=500mA, 480M]
`-- 1-1: Integrated_Webcam_FHD [500mA, bus-pwr, 480M]
usb3: xHCI Host Controller [subtree=200mA, 480M]
|-- 3-3: 58200 [100mA, self-pwr, 480M]
`-- 3-4: Wireless_Device [100mA, self-pwr, 480M]
usb7: xHCI Host Controller [subtree=190mA, 480M]
`-- 7-1: USB2.1 Hub [0mA, self-pwr, subtree=190mA, 480M]
    |-- 7-1.2: USB2.0 4 Port HUB [0mA, self-pwr, subtree=90mA, 480M]
    |   `-- 7-1.2.4: USB2.0 4 Port HUB [0mA, self-pwr, subtree=90mA, 480M]
    |       `-- 7-1.2.4.4: FT232R USB UART [90mA, bus-pwr, 12M]
    `-- 7-1.4: HID Device [100mA, self-pwr, 480M]

### channel 1 ON
(pqsign) sru@riou-sebastien-pqshield:~/repos/pqsign$ ./tools/usb-power-check 
USB topology:
usb1: xHCI Host Controller [subtree=500mA, 480M]
`-- 1-1: Integrated_Webcam_FHD [500mA, bus-pwr, 480M]
usb3: xHCI Host Controller [subtree=200mA, 480M]
|-- 3-3: 58200 [100mA, self-pwr, 480M]
`-- 3-4: Wireless_Device [100mA, self-pwr, 480M]
usb7: xHCI Host Controller [subtree=290mA, 480M]
`-- 7-1: USB2.1 Hub [0mA, self-pwr, subtree=290mA, 480M]
    |-- 7-1.2: USB2.0 4 Port HUB [0mA, self-pwr, subtree=190mA, 480M]
    |   |-- 7-1.2.1: Lenovo Precision USB Mouse [100mA, bus-pwr, 1.5M]
    |   `-- 7-1.2.4: USB2.0 4 Port HUB [0mA, self-pwr, subtree=90mA, 480M]
    |       `-- 7-1.2.4.4: FT232R USB UART [90mA, bus-pwr, 12M]
    `-- 7-1.4: HID Device [100mA, self-pwr, 480M]

### channel 2 ON
(pqsign) sru@riou-sebastien-pqshield:~/repos/pqsign$ ./tools/usb-power-check 
USB topology:
usb1: xHCI Host Controller [subtree=500mA, 480M]
`-- 1-1: Integrated_Webcam_FHD [500mA, bus-pwr, 480M]
usb3: xHCI Host Controller [subtree=200mA, 480M]
|-- 3-3: 58200 [100mA, self-pwr, 480M]
`-- 3-4: Wireless_Device [100mA, self-pwr, 480M]
usb7: xHCI Host Controller [subtree=290mA, 480M]
`-- 7-1: USB2.1 Hub [0mA, self-pwr, subtree=290mA, 480M]
    |-- 7-1.2: USB2.0 4 Port HUB [0mA, self-pwr, subtree=190mA, 480M]
    |   |-- 7-1.2.2: Lenovo Precision USB Mouse [100mA, bus-pwr, 1.5M]
    |   `-- 7-1.2.4: USB2.0 4 Port HUB [0mA, self-pwr, subtree=90mA, 480M]
    |       `-- 7-1.2.4.4: FT232R USB UART [90mA, bus-pwr, 12M]
    `-- 7-1.4: HID Device [100mA, self-pwr, 480M]

## channel 3 ON
(pqsign) sru@riou-sebastien-pqshield:~/repos/pqsign$ ./tools/usb-power-check 
USB topology:
usb1: xHCI Host Controller [subtree=500mA, 480M]
`-- 1-1: Integrated_Webcam_FHD [500mA, bus-pwr, 480M]
usb3: xHCI Host Controller [subtree=200mA, 480M]
|-- 3-3: 58200 [100mA, self-pwr, 480M]
`-- 3-4: Wireless_Device [100mA, self-pwr, 480M]
usb7: xHCI Host Controller [subtree=290mA, 480M]
`-- 7-1: USB2.1 Hub [0mA, self-pwr, subtree=290mA, 480M]
    |-- 7-1.2: USB2.0 4 Port HUB [0mA, self-pwr, subtree=190mA, 480M]
    |   |-- 7-1.2.3: Lenovo Precision USB Mouse [100mA, bus-pwr, 1.5M]
    |   `-- 7-1.2.4: USB2.0 4 Port HUB [0mA, self-pwr, subtree=90mA, 480M]
    |       `-- 7-1.2.4.4: FT232R USB UART [90mA, bus-pwr, 12M]
    `-- 7-1.4: HID Device [100mA, self-pwr, 480M]

## channel 4 ON
(pqsign) sru@riou-sebastien-pqshield:~/repos/pqsign$ ./tools/usb-power-check 
USB topology:
usb1: xHCI Host Controller [subtree=500mA, 480M]
`-- 1-1: Integrated_Webcam_FHD [500mA, bus-pwr, 480M]
usb3: xHCI Host Controller [subtree=200mA, 480M]
|-- 3-3: 58200 [100mA, self-pwr, 480M]
`-- 3-4: Wireless_Device [100mA, self-pwr, 480M]
usb7: xHCI Host Controller [subtree=290mA, 480M]
`-- 7-1: USB2.1 Hub [0mA, self-pwr, subtree=290mA, 480M]
    |-- 7-1.2: USB2.0 4 Port HUB [0mA, self-pwr, subtree=190mA, 480M]
    |   `-- 7-1.2.4: USB2.0 4 Port HUB [0mA, self-pwr, subtree=190mA, 480M]
    |       |-- 7-1.2.4.1: Lenovo Precision USB Mouse [100mA, bus-pwr, 1.5M]
    |       `-- 7-1.2.4.4: FT232R USB UART [90mA, bus-pwr, 12M]
    `-- 7-1.4: HID Device [100mA, self-pwr, 480M]

## channel 5 ON
(pqsign) sru@riou-sebastien-pqshield:~/repos/pqsign$ ./tools/usb-power-check 
USB topology:
usb1: xHCI Host Controller [subtree=500mA, 480M]
`-- 1-1: Integrated_Webcam_FHD [500mA, bus-pwr, 480M]
usb3: xHCI Host Controller [subtree=200mA, 480M]
|-- 3-3: 58200 [100mA, self-pwr, 480M]
`-- 3-4: Wireless_Device [100mA, self-pwr, 480M]
usb7: xHCI Host Controller [subtree=290mA, 480M]
`-- 7-1: USB2.1 Hub [0mA, self-pwr, subtree=290mA, 480M]
    |-- 7-1.2: USB2.0 4 Port HUB [0mA, self-pwr, subtree=190mA, 480M]
    |   `-- 7-1.2.4: USB2.0 4 Port HUB [0mA, self-pwr, subtree=190mA, 480M]
    |       |-- 7-1.2.4.2: Lenovo Precision USB Mouse [100mA, bus-pwr, 1.5M]
    |       `-- 7-1.2.4.4: FT232R USB UART [90mA, bus-pwr, 12M]
    `-- 7-1.4: HID Device [100mA, self-pwr, 480M]

## channel 6 ON
(pqsign) sru@riou-sebastien-pqshield:~/repos/pqsign$ ./tools/usb-power-check 
USB topology:
usb1: xHCI Host Controller [subtree=500mA, 480M]
`-- 1-1: Integrated_Webcam_FHD [500mA, bus-pwr, 480M]
usb3: xHCI Host Controller [subtree=200mA, 480M]
|-- 3-3: 58200 [100mA, self-pwr, 480M]
`-- 3-4: Wireless_Device [100mA, self-pwr, 480M]
usb7: xHCI Host Controller [subtree=290mA, 480M]
`-- 7-1: USB2.1 Hub [0mA, self-pwr, subtree=290mA, 480M]
    |-- 7-1.2: USB2.0 4 Port HUB [0mA, self-pwr, subtree=190mA, 480M]
    |   `-- 7-1.2.4: USB2.0 4 Port HUB [0mA, self-pwr, subtree=190mA, 480M]
    |       |-- 7-1.2.4.3: Lenovo Precision USB Mouse [100mA, bus-pwr, 1.5M]
    |       `-- 7-1.2.4.4: FT232R USB UART [90mA, bus-pwr, 12M]
    `-- 7-1.4: HID Device [100mA, self-pwr, 480M]

## channel 7 ON
Requires a 5Gbps device, could not test.

## channel 1 to 6 ON
Here various devices, including a hub, are connected to channels 1 to 6

(pqsign) sru@riou-sebastien-pqshield:~/repos/pqsign$ ./tools/usb-power-check 
USB topology:
usb1: xHCI Host Controller [subtree=500mA, 480M]
`-- 1-1: Integrated_Webcam_FHD [500mA, bus-pwr, 480M]
usb3: xHCI Host Controller [subtree=200mA, 480M]
|-- 3-3: 58200 [100mA, self-pwr, 480M]
`-- 3-4: Wireless_Device [100mA, self-pwr, 480M]
usb7: xHCI Host Controller [subtree=1440mA, 480M]
`-- 7-1: USB2.1 Hub [0mA, self-pwr, subtree=1440mA, 480M]
    |-- 7-1.2: USB2.0 4 Port HUB [0mA, self-pwr, subtree=1340mA, 480M]
    |   |-- 7-1.2.1: Lenovo Precision USB Mouse [100mA, bus-pwr, 1.5M]
    |   |-- 7-1.2.2: HID DEVICE [0mA, self-pwr, 12M]
    |   |-- 7-1.2.3: STLINK-V3 [500mA, bus-pwr, 480M]
    |   `-- 7-1.2.4: USB2.0 4 Port HUB [0mA, self-pwr, subtree=740mA, 480M]
    |       |-- 7-1.2.4.1: USB2.1 Hub [100mA, self-pwr, subtree=200mA, 480M]
    |       |   |-- 7-1.2.4.1.1: USB2.1 Hub [100mA, self-pwr, subtree=0mA, 480M]
    |       |   `-- 7-1.2.4.1.2: USB2.1 Hub [100mA, self-pwr, subtree=0mA, 480M]
    |       |-- 7-1.2.4.2: Nu-Link2 CMSIS-DAP [100mA, bus-pwr, 480M]
    |       |-- 7-1.2.4.3: Pico [250mA, bus-pwr, 12M]
    |       `-- 7-1.2.4.4: FT232R USB UART [90mA, bus-pwr, 12M]
    `-- 7-1.4: HID Device [100mA, self-pwr, 480M]


## a real world snopshot

### lsusb -t
````
sru@riou-sebastien-pqshield:~/repos/usbman$ lsusb -t
/:  Bus 001.Port 001: Dev 001, Class=root_hub, Driver=xhci_hcd/1p, 480M
    |__ Port 001: Dev 002, If 0, Class=Video, Driver=uvcvideo, 480M
    |__ Port 001: Dev 002, If 1, Class=Video, Driver=uvcvideo, 480M
    |__ Port 001: Dev 002, If 2, Class=Video, Driver=uvcvideo, 480M
    |__ Port 001: Dev 002, If 3, Class=Video, Driver=uvcvideo, 480M
    |__ Port 001: Dev 002, If 4, Class=Application Specific Interface, Driver=[none], 480M
/:  Bus 002.Port 001: Dev 001, Class=root_hub, Driver=xhci_hcd/1p, 10000M
/:  Bus 003.Port 001: Dev 001, Class=root_hub, Driver=xhci_hcd/5p, 480M
    |__ Port 003: Dev 003, If 0, Class=Application Specific Interface, Driver=[none], 480M
    |__ Port 004: Dev 005, If 0, Class=Wireless, Driver=btusb, 480M
    |__ Port 004: Dev 005, If 1, Class=Wireless, Driver=btusb, 480M
    |__ Port 004: Dev 005, If 2, Class=Wireless, Driver=btusb, 480M
/:  Bus 004.Port 001: Dev 001, Class=root_hub, Driver=xhci_hcd/2p, 10000M
/:  Bus 005.Port 001: Dev 001, Class=root_hub, Driver=xhci_hcd/1p, 480M
/:  Bus 006.Port 001: Dev 001, Class=root_hub, Driver=xhci_hcd/1p, 10000M
/:  Bus 007.Port 001: Dev 001, Class=root_hub, Driver=xhci_hcd/1p, 480M
    |__ Port 001: Dev 065, If 0, Class=Hub, Driver=hub/4p, 480M
        |__ Port 002: Dev 075, If 0, Class=Hub, Driver=hub/4p, 480M
            |__ Port 001: Dev 086, If 0, Class=Human Interface Device, Driver=usbhid, 1.5M
            |__ Port 002: Dev 090, If 0, Class=Human Interface Device, Driver=usbhid, 12M
            |__ Port 003: Dev 089, If 0, Class=Vendor Specific Class, Driver=[none], 480M
            |__ Port 003: Dev 089, If 1, Class=Communications, Driver=cdc_acm, 480M
            |__ Port 003: Dev 089, If 2, Class=CDC Data, Driver=cdc_acm, 480M
            |__ Port 004: Dev 078, If 0, Class=Hub, Driver=hub/4p, 480M
                |__ Port 001: Dev 091, If 0, Class=Hub, Driver=hub/4p, 480M
                    |__ Port 001: Dev 092, If 0, Class=Hub, Driver=hub/4p, 480M
                    |__ Port 002: Dev 093, If 0, Class=Hub, Driver=hub/4p, 480M
                |__ Port 002: Dev 088, If 0, Class=Vendor Specific Class, Driver=[none], 480M
                |__ Port 002: Dev 088, If 1, Class=Communications, Driver=cdc_acm, 480M
                |__ Port 002: Dev 088, If 2, Class=CDC Data, Driver=cdc_acm, 480M
                |__ Port 002: Dev 088, If 3, Class=Human Interface Device, Driver=usbhid, 480M
                |__ Port 002: Dev 088, If 4, Class=Vendor Specific Class, Driver=[none], 480M
                |__ Port 002: Dev 088, If 5, Class=Mass Storage, Driver=usb-storage, 480M
                |__ Port 003: Dev 087, If 0, Class=Communications, Driver=cdc_acm, 12M
                |__ Port 003: Dev 087, If 1, Class=CDC Data, Driver=cdc_acm, 12M
                |__ Port 003: Dev 087, If 2, Class=Vendor Specific Class, Driver=[none], 12M
                |__ Port 004: Dev 079, If 0, Class=Vendor Specific Class, Driver=ftdi_sio, 12M
        |__ Port 004: Dev 066, If 0, Class=Human Interface Device, Driver=usbhid, 480M
/:  Bus 008.Port 001: Dev 001, Class=root_hub, Driver=xhci_hcd/1p, 10000M
````

## /dev/serial
````
sru@riou-sebastien-pqshield:~/repos/usbman$ tree /dev/serial/
/dev/serial/
├── by-id
│   ├── usb-FTDI_FT232R_USB_UART_B001DNH6-if00-port0 -> ../../ttyUSB0
│   ├── usb-Nuvoton_Nu-Link2_CMSIS-DAP_13150000000A25020450395D00000FCD-if01 -> ../../ttyACM1
│   ├── usb-Raspberry_Pi_Pico_648326155B4B110B-if00 -> ../../ttyACM0
│   └── usb-STMicroelectronics_STLINK-V3_003800163233511939363634-if01 -> ../../ttyACM2
└── by-path
    ├── pci-0000:c6:00.4-usb-0:1.2.3:1.1 -> ../../ttyACM2
    ├── pci-0000:c6:00.4-usb-0:1.2.4.2:1.1 -> ../../ttyACM1
    ├── pci-0000:c6:00.4-usb-0:1.2.4.3:1.0 -> ../../ttyACM0
    ├── pci-0000:c6:00.4-usb-0:1.2.4.4:1.0-port0 -> ../../ttyUSB0
    ├── pci-0000:c6:00.4-usbv2-0:1.2.3:1.1 -> ../../ttyACM2
    ├── pci-0000:c6:00.4-usbv2-0:1.2.4.2:1.1 -> ../../ttyACM1
    ├── pci-0000:c6:00.4-usbv2-0:1.2.4.3:1.0 -> ../../ttyACM0
    └── pci-0000:c6:00.4-usbv2-0:1.2.4.4:1.0-port0 -> ../../ttyUSB0
````

## Mapping serial devices to channels
- ttyACM0 --> channel 6
- ttyACM1 --> channel 5
- ttyACM2 --> channel 3
