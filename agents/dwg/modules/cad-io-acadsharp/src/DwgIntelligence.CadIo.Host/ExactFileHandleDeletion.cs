using System.ComponentModel;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

internal readonly record struct FileIdentity(
    uint VolumeSerialNumber,
    ulong FileIndex);

internal static class ExactFileHandleDeletion
{
    private const uint DeleteAccess = 0x00010000;
    private const uint FileReadAttributes = 0x00000080;
    private const uint GenericRead = 0x80000000;
    private const uint GenericWrite = 0x40000000;
    private const uint ShareRead = 0x00000001;
    private const uint ShareWrite = 0x00000002;
    private const uint ShareDelete = 0x00000004;
    private const uint CreateNew = 1;
    private const uint OpenExisting = 3;
    private const uint FileAttributeNormal = 0x00000080;
    private const int FileDispositionInfo = 4;

    internal static FileStream CreateNewReadWrite(string path)
    {
        EnsureWindows();
        SafeFileHandle handle = CreateFileW(
            path,
            GenericRead | GenericWrite | DeleteAccess,
            ShareRead | ShareWrite | ShareDelete,
            IntPtr.Zero,
            CreateNew,
            FileAttributeNormal,
            IntPtr.Zero);
        if (handle.IsInvalid)
        {
            throw LastWin32Exception();
        }
        try
        {
            return new FileStream(handle, FileAccess.ReadWrite);
        }
        catch
        {
            handle.Dispose();
            throw;
        }
    }

    internal static FileIdentity GetIdentity(SafeFileHandle handle)
    {
        EnsureWindows();
        if (!GetFileInformationByHandle(
            handle,
            out ByHandleFileInformation information))
        {
            throw LastWin32Exception();
        }
        return new FileIdentity(
            information.VolumeSerialNumber,
            ((ulong)information.FileIndexHigh << 32)
                | information.FileIndexLow);
    }

    internal static void DeleteVerifiedPath(
        string path,
        FileIdentity expected,
        Action<string>? afterIdentityVerified)
    {
        EnsureWindows();
        using SafeFileHandle handle = CreateFileW(
            path,
            DeleteAccess | FileReadAttributes,
            ShareRead | ShareWrite | ShareDelete,
            IntPtr.Zero,
            OpenExisting,
            FileAttributeNormal,
            IntPtr.Zero);
        if (handle.IsInvalid)
        {
            throw LastWin32Exception();
        }
        if (GetIdentity(handle) != expected)
        {
            throw new IOException("Owned file identity changed.");
        }
        afterIdentityVerified?.Invoke(path);
        MarkDelete(handle);
    }

    internal static void DeleteOpenHandle(
        FileStream stream,
        FileIdentity expected)
    {
        if (GetIdentity(stream.SafeFileHandle) != expected)
        {
            throw new IOException("Owned file identity changed.");
        }
        MarkDelete(stream.SafeFileHandle);
    }

    private static void MarkDelete(SafeFileHandle handle)
    {
        var disposition = new FileDispositionInformation
        {
            DeleteFile = 1
        };
        if (!SetFileInformationByHandle(
            handle,
            FileDispositionInfo,
            ref disposition,
            (uint)Marshal.SizeOf<FileDispositionInformation>()))
        {
            throw LastWin32Exception();
        }
    }

    private static void EnsureWindows()
    {
        if (!OperatingSystem.IsWindows())
        {
            throw new PlatformNotSupportedException(
                "Exact probe file cleanup requires Windows handles.");
        }
    }

    private static Win32Exception LastWin32Exception()
    {
        return new Win32Exception(Marshal.GetLastWin32Error());
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct FileDispositionInformation
    {
        public byte DeleteFile;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct ByHandleFileInformation
    {
        public uint FileAttributes;
        public System.Runtime.InteropServices.ComTypes.FILETIME CreationTime;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastAccessTime;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWriteTime;
        public uint VolumeSerialNumber;
        public uint FileSizeHigh;
        public uint FileSizeLow;
        public uint NumberOfLinks;
        public uint FileIndexHigh;
        public uint FileIndexLow;
    }

    [DllImport(
        "kernel32.dll",
        CharSet = CharSet.Unicode,
        SetLastError = true)]
    private static extern SafeFileHandle CreateFileW(
        string fileName,
        uint desiredAccess,
        uint shareMode,
        IntPtr securityAttributes,
        uint creationDisposition,
        uint flagsAndAttributes,
        IntPtr templateFile);

    [DllImport(
        "kernel32.dll",
        SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetFileInformationByHandle(
        SafeFileHandle file,
        out ByHandleFileInformation fileInformation);

    [DllImport(
        "kernel32.dll",
        SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetFileInformationByHandle(
        SafeFileHandle file,
        int fileInformationClass,
        ref FileDispositionInformation fileInformation,
        uint bufferSize);
}
