// 读取/设置内置扬声器音量与静音。用法: spkvol            -> 读取
//                                 spkvol set 0.5    -> 设音量(0-1)并取消静音
import CoreAudio
import Foundation

func prop(_ sel: AudioObjectPropertySelector, _ scope: AudioObjectPropertyScope, _ el: UInt32 = 0) -> AudioObjectPropertyAddress {
    AudioObjectPropertyAddress(mSelector: sel, mScope: scope, mElement: el)
}
var addr = prop(kAudioHardwarePropertyDevices, kAudioObjectPropertyScopeGlobal)
var size: UInt32 = 0
AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size)
var ids = [AudioDeviceID](repeating: 0, count: Int(size) / MemoryLayout<AudioDeviceID>.size)
AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size, &ids)
for id in ids {
    var uidAddr = prop(kAudioDevicePropertyDeviceUID, kAudioObjectPropertyScopeGlobal)
    var uid: Unmanaged<CFString>?
    var s = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
    guard AudioObjectGetPropertyData(id, &uidAddr, 0, nil, &s, &uid) == noErr,
          let u = uid?.takeRetainedValue() as String?, u == "BuiltInSpeakerDevice" else { continue }
    let args = CommandLine.arguments
    for el: UInt32 in [0, 1, 2] {
        var va = prop(kAudioDevicePropertyVolumeScalar, kAudioDevicePropertyScopeOutput, el)
        var ma = prop(kAudioDevicePropertyMute, kAudioDevicePropertyScopeOutput, el)
        if args.count >= 3 && args[1] == "set" {
            var v = Float32(Double(args[2]) ?? 0.5); var m: UInt32 = 0
            if AudioObjectHasProperty(id, &va) { AudioObjectSetPropertyData(id, &va, 0, nil, UInt32(MemoryLayout<Float32>.size), &v) }
            if AudioObjectHasProperty(id, &ma) { AudioObjectSetPropertyData(id, &ma, 0, nil, UInt32(MemoryLayout<UInt32>.size), &m) }
        }
        var v: Float32 = -1; var vs = UInt32(MemoryLayout<Float32>.size)
        var m: UInt32 = 99; var ms = UInt32(MemoryLayout<UInt32>.size)
        let hv = AudioObjectHasProperty(id, &va), hm = AudioObjectHasProperty(id, &ma)
        if hv { AudioObjectGetPropertyData(id, &va, 0, nil, &vs, &v) }
        if hm { AudioObjectGetPropertyData(id, &ma, 0, nil, &ms, &m) }
        print("element \(el): volume \(hv ? String(v) : "n/a")  mute \(hm ? String(m) : "n/a")")
    }
}
