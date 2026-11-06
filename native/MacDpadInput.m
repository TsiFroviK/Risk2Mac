#import <Foundation/Foundation.h>
#import <GameController/GameController.h>

// Unity's main run loop services GameController connection/state notifications.
// No background input, callbacks, synthetic events or persistent controller pointer.
__attribute__((visibility("default"))) int ror2_mac_dpad(float *x, float *y) {
    if (!x || !y) return 0;
    *x = *y = 0;
    @autoreleasepool {
        int count = 0;
        float dx = 0, dy = 0;
        for (GCController *controller in GCController.controllers) {
            NSString *name = controller.vendorName;
            BOOL matches = [name caseInsensitiveCompare:@"Xbox Wireless Controller"] == NSOrderedSame ||
                [name caseInsensitiveCompare:@"Microsoft Xbox Wireless Controller"] == NSOrderedSame;
            if (!name || !matches || !controller.extendedGamepad) continue;
            count++;
            dx = controller.extendedGamepad.dpad.xAxis.value;
            dy = controller.extendedGamepad.dpad.yAxis.value;
        }
        if (count == 1) { *x = dx; *y = dy; }
        return count;
    }
}
