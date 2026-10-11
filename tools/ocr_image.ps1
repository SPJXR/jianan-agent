# OCR 一张图片 -> 输出识别文本（Windows.Media.Ocr, zh-Hans-CN）
param([string]$Image, [string]$OutText)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    try {
        $netTask.Wait(-1) | Out-Null
    } catch {
        $inner = $_.Exception.InnerException.InnerException
        if ($inner) { Write-Output ("AWAIT_ERR hresult=" + ('{0:X}' -f $inner.HResult) + " :: " + $inner.Message) }
        throw
    }
    $netTask.Result
}

[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.Streams.DataWriter, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null

$lang = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage("zh-Hans-CN")
if ($null -eq $lang) { Write-Output "OCR_LANG_FAIL"; exit 1 }

$bytes = [System.IO.File]::ReadAllBytes($Image)
$mem = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
$writer = New-Object Windows.Storage.Streams.DataWriter($mem.GetOutputStreamAt(0))
$writer.WriteBytes($bytes)
$null = Await ($writer.StoreAsync()) ([UInt32])
$null = Await ($writer.FlushAsync()) ([Boolean])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($mem)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
if ($bitmap.BitmapPixelFormat -ne [Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8) {
    $bitmap = [Windows.Graphics.Imaging.SoftwareBitmap]::Convert(
        $bitmap, [Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8,
        [Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied)
}
$ocrResult = Await ($lang.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
$text = $ocrResult.Text
[System.IO.File]::WriteAllText($OutText, $text, [System.Text.Encoding]::UTF8)
Write-Output ("OCR_CHARS=" + $text.Length)
