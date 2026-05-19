'use strict';

const fs   = require('fs');
const path = require('path');

const OUTPUT_DIR = process.argv[2] || path.join(__dirname, '../../output');
const V86_FILES  = path.join(__dirname, '../v86files');
const STATE_FILE = path.join(OUTPUT_DIR, 'state.bin');

// libv86.mjs is the ES module build with native Node.js support — no polyfills needed.
// dynamic import() works inside a CommonJS file on Node 14+.
import(path.join(V86_FILES, 'libv86.mjs')).then(({ V86 }) => {

    console.log('Booting VM to generate save state...');
    console.log('(Waiting for V86_SYSTEM_READY signal on serial — may take several minutes with a desktop)\n');

    const emulator = new V86({
        wasm_path: path.join(V86_FILES, 'v86.wasm'),
        bios:     { url: path.join(V86_FILES, 'seabios.bin') },
        vga_bios: { url: path.join(V86_FILES, 'vgabios.bin') },

        autostart:       true,
        memory_size:     256 * 1024 * 1024,
        vga_memory_size: 4   * 1024 * 1024,

        bzimage_initrd_from_filesystem: true,
        cmdline: 'rw root=host9p rootfstype=9p rootflags=trans=virtio,cache=loose modules=virtio_pci tsc=reliable console=ttyS0,115200',

        filesystem: {
            baseurl: path.join(OUTPUT_DIR, 'rootfs-flat'),
            basefs:  path.join(OUTPUT_DIR, 'rootfs-fs.json'),
        },

        disable_mouse: true,
    });

    let serial_text = '';
    let saved       = false;

    emulator.add_listener('serial0-output-byte', function(byte)
    {
        const c = String.fromCharCode(byte);
        process.stdout.write(c);
        serial_text += c;

        if (!saved && serial_text.includes('V86_SYSTEM_READY'))
        {
            saved = true;
            console.log('\n[state] V86_SYSTEM_READY received — flushing caches and saving state...');
            // Drop page cache to reduce state size; sync already called by the in-VM marker script.
            emulator.serial0_send('echo 3 >/proc/sys/vm/drop_caches\n');

            setTimeout(async function()
            {
                console.log('[state] Saving state to ' + STATE_FILE + ' ...');
                const s = await emulator.save_state();
                fs.writeFileSync(STATE_FILE, new Uint8Array(s));
                console.log('[state] Saved (' + (s.byteLength / 1024 / 1024).toFixed(1) + ' MB)');
                emulator.destroy();
                process.exit(0);
            }, 3 * 1000);
        }
    });

    // 15-minute timeout — generous enough for a desktop to fully start.
    setTimeout(() => {
        if (!saved) {
            process.stderr.write('\n[state] Timeout: VM did not emit V86_SYSTEM_READY within 15 minutes.\n');
            process.stderr.write('Last serial output:\n' + serial_text.slice(-2000) + '\n');
            process.exit(1);
        }
    }, 15 * 60 * 1000);

}).catch(err => {
    process.stderr.write('Failed to load libv86.mjs: ' + err.message + '\n');
    process.stderr.write('Make sure libv86.mjs is present in ' + V86_FILES + '\n');
    process.exit(1);
});
